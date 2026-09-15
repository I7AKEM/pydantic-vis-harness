"""Evaluate scripted lead conversations; run with --corpus for ten seed-11 corpus questions."""

import argparse
import asyncio
import json
import os
import random
import math
import re
import shutil
import tempfile
from time import perf_counter
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from pydantic_ai import capture_run_messages
from pydantic_ai.messages import ToolCallPart, ToolReturnPart, ModelMessagesTypeAdapter
from pydantic_core import to_jsonable_python

from evals.designer.agent.corpus_tools.select import CORPUS, read_manifest
from vis_agent.analyst.agent import ARABIC, DEFAULT_ANALYST_MODEL, create_analyst
from vis_agent.analyst.checks import numeric_mention_direction
from vis_agent.deps import AppDeps
from vis_agent.designer.agent import DEFAULT_DESIGNER_MODEL, DEFAULT_FALLBACK_DESIGNER_MODEL, create_designer
import vis_agent.lead
from vis_agent.lead import create_lead
from vis_agent.models import DataBrief
from vis_agent.profiler.agent import DEFAULT_PROFILER_MODEL, create_profiler, profile_dataset
from vis_agent.requests.store import RequestStore
from vis_agent.store import DatasetStore
from vis_agent.units import COUNT_NOUNS, canonical_unit, display_unit
from vis_agent.designer.syntax import parse
from vis_agent.designer.models import SpecError
from evals.analyst.run import tables_match
from evals.designer.agent.indicator.scoring import numeric_text_matches

ROOT = Path(__file__).resolve().parents[2]
DATA_TOOLS = {"draw", "answer_question", "revise", "resume"}


def load_cases(path: Path | None = None) -> list[dict]:
    # Cases marked heldout are evaluation-only; exclude them from any future prompt tuning.
    return json.loads((path or Path(__file__).with_name("cases.json")).read_text(encoding="utf-8"))


def observed_outcome(value: dict, last_tool: str) -> str:
    artifact = value.get("artifact")
    if value.get("status") == "failed" or value.get("error"):
        return "failure"
    if value.get("clarification"):
        return "clarification"
    if artifact:
        if artifact.get("no_chart_reason"):
            return "fallback_table"
        if artifact.get("chart") == "indicator":
            return "unavailable_indicator" if any(cell is None for row in artifact.get("rows", []) for cell in row) else "indicator"
        return "artifact"
    return "table" if last_tool == "answer_question" and value.get("rows") else "text"


def metric_values_match(expected: dict, artifact: dict) -> bool:
    """Check e2e numeric bindings without requiring a model's SQL aliases to match gold aliases."""
    try:
        spec = parse(artifact["spec"])
        if spec.type != "indicator" or len(spec.cards) != expected["card_count"]:
            return False
        columns = artifact["columns"]
        metadata = {column["name"]: column for column in columns}
        if artifact.get("row_count") != 1 or len(artifact["rows"]) != 1:
            return False
        row = dict(zip(metadata, artifact["rows"][0]))
        actual = [(row[c.value], metadata[c.value].get("unit")) for c in spec.cards]
        wanted = list(zip(expected["values"], expected.get("units", [None] * expected["card_count"])))
        def equal(a, b):
            return a is None and b is None or isinstance(a, (int, float)) and not isinstance(a, bool) and b is not None and math.isclose(a, b, rel_tol=1e-7, abs_tol=1e-10)
        def dimension(unit):
            if unit is not None and any(unit.strip().casefold() in aliases for aliases, *_ in COUNT_NOUNS.values()):
                return None
            return canonical_unit(display_unit(unit))
        def unit_matches(actual, expected):
            for aliases, *_ in COUNT_NOUNS.values():
                if expected is not None and expected.strip().casefold() in aliases:
                    return actual is not None and actual.strip().casefold() in aliases
            return dimension(actual) == dimension(expected)
        for number, unit in wanted:
            match = next((i for i, (value, actual_unit) in enumerate(actual) if equal(value, number) and unit_matches(actual_unit, unit)), None)
            if match is None:
                return False
            actual.pop(match)
        support = [row[name] for c in spec.cards for name in c.support]
        return all(any(equal(value, expected) for value in support) for expected in expected.get("support_values", []))
    except (KeyError, TypeError, ValueError, SpecError):
        return False


def answer_numbers_match(reply: str | None, artifact: dict, question: str) -> bool:
    """Check numeric claims against saved values, without permitting implicit 100x scaling.

    This is a factual check, not a judge of whether the wording explains the answer well.
    Links/IDs and list ordinals are removed before examining user-visible claims.
    """
    if not reply:
        return False
    text = re.sub(r"\]\([^)]*\)", "]", reply)
    text = re.sub(r"\b(?:art|rq|ds)_[A-Za-z0-9]+\b|#[A-Fa-f0-9]{6}\b", "", text)
    text = re.sub(r"^\s*\d+[.)]\s+", "", text, flags=re.MULTILINE)
    text = text.replace("−", "-")
    number = re.compile(r"[-+]?(?:\d[\d,٬]*)(?:[.٫]\d+)?(?:[eE][-+]?\d+)?(?:[KMBT])?")
    context = set(number.findall(question + " " + (artifact.get("question") or "")))
    # Runtime warnings can quote verified source totals that are outside the filtered result.
    for warning in artifact.get("warnings", []):
        context.update(number.findall(warning))
    candidates = [v for row in artifact.get("rows", []) for v in row
                  if isinstance(v, (int, float)) and not isinstance(v, bool)]
    signed_values = list(candidates)
    candidates.extend(artifact[key] for key in ("row_count", "version") if isinstance(artifact.get(key), int))
    for row in artifact.get("rows", []):
        for value in row:
            if isinstance(value, str):
                context.update(number.findall(value))
    for mention in number.finditer(text):
        token = mention[0]
        start = mention.start() + (1 if token.startswith('+') else 0)
        direction = numeric_mention_direction(text, start, mention.end())
        if direction == 0:
            return False
        if direction is not None:
            signed = ('-' if direction == -1 else '') + token.lstrip('+')
            if not any(numeric_text_matches(signed, value) for value in signed_values):
                return False
        elif token not in context and not any(numeric_text_matches(token, value) for value in candidates):
            return False
    return True


def corpus_cases(corpus: Path = CORPUS) -> list[dict]:
    # Preserve manifest order before sampling, as in the Phase 4b lead sample.
    rows = random.Random(11).sample(read_manifest(corpus / "manifest.jsonl"), 10)
    cases = []
    for row in rows:
        csv = corpus / row["csv_path"]
        question = row["occurrences"][0]["question"]
        cases.append({
            "name": "corpus-" + row["dataset_id"], "csv": str(csv),
            "turns": [{"message": question + "\n\nAttached CSV: [" + csv.name
                       + "](/datasets/{dataset_id}/profile)",
                       "tool": ["draw", "answer_question"], "outcome": "answered"}],
        })
    return cases


def score_turn(expected: dict, messages: list, reply: str | None = None) -> dict:
    parts = [part for message in messages for part in message.parts]
    calls = [part for part in parts if isinstance(part, ToolCallPart)]
    data_calls = [part for part in calls if part.tool_name in DATA_TOOLS]
    # The tool choice is the first data call of the turn; the outcome is the last one's, since a lead that
    # retries after a specialist failure delivers what the user sees.
    call = data_calls[0] if data_calls else None
    last = data_calls[-1] if data_calls else None
    returned = next((part for part in parts if isinstance(part, ToolReturnPart) and last is not None
                     and part.tool_call_id == last.tool_call_id and part.tool_name == last.tool_name), None)
    content = returned.content if returned is not None else None
    if hasattr(content, "model_dump"):
        content = content.model_dump(mode="json")
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except ValueError:
            pass
    value = content if isinstance(content, dict) else {}
    tool = call.tool_name if call is not None else "none"
    args = call.args_as_dict() if call is not None else {}
    last_tool = last.tool_name if last is not None else "none"
    artifact = value.get("artifact")
    questioned = value.get("clarification") is not None
    outcomes = {
        "artifact": artifact is not None,
        # Repair cases accept a delivered artifact, including a table when a chart cannot fit.
        "chart": artifact is not None,
        "question": questioned,
        "artifact_or_question": artifact is not None or questioned,
        # A corpus question over a result-table export may be drawn, asked about, or answered with a table.
        "answered": artifact is not None or questioned
        or (last_tool == "answer_question" and bool(value.get("rows"))),
        "table": last_tool == "answer_question" and bool(value.get("rows")),
        # The lead answered in words: no data tool, or one that returned neither an artifact nor a question
        # (a resume with nothing to continue, for example).
        "text": call is None or (artifact is None and not questioned),
        "indicator": isinstance(artifact, dict) and artifact.get("chart") == "indicator"
        and bool(artifact.get("png_url")) and not artifact.get("no_chart_reason"),
        "failure": observed_outcome(value, last_tool) == "failure",
        "fallback": observed_outcome(value, last_tool) == "fallback_table",
    }
    accepted = expected["tool"] if isinstance(expected["tool"], list) else [expected["tool"]]
    # redo_analysis is judged only when a revision was expected and made; a turn that accepts resume or
    # revise (an answer that may continue a question or change a delivered chart) judges it on revise alone.
    redo_ok = None
    if "redo_analysis" in expected and (tool == "revise" or not isinstance(expected["tool"], list)):
        redo_ok = tool == "revise" and args.get("redo_analysis") is expected["redo_analysis"]
    fidelity_ok = metric_values_match(expected["metrics"], artifact or {}) if "metrics" in expected else None
    if expected.get("forbid_indicator"):
        fidelity_ok = bool(artifact) and artifact.get("chart") != "indicator"
    if "expected_rows" in expected:
        rows = value.get("rows") or []
        fidelity_ok = bool(rows) and bool(tables_match({"columns": list(range(len(expected["expected_rows"][0]))),
            "rows": expected["expected_rows"], "strict_scale": True},
            {"columns": list(range(len(rows[0]))), "rows": rows}))
    delivery_ok = None
    if expected.get("require_delivery"):
        delivery_ok = bool(reply and artifact and artifact.get("png_url") and artifact["png_url"] in reply)
    if expected.get("no_image"):
        delivery_ok = bool(reply) and not bool(re.search(r"!\[|/renders/[^\s)]+\.png", reply))
    answer_fidelity_ok = answer_numbers_match(reply, artifact or {}, expected.get("message", "")) if "metrics" in expected else None
    language_ok = None
    if expected.get("language"):
        try:
            spec = parse((artifact or {})["spec"])
            language_ok = spec.language == expected["language"] and (
                bool(ARABIC.search(spec.title or "")) if expected["language"] == "ar"
                else not bool(ARABIC.search(spec.title or "")))
        except (KeyError, TypeError, SpecError):
            language_ok = False
    return {
        "tool": tool, "tool_ok": tool in accepted,
        "redo_ok": redo_ok,
        "outcome_ok": outcomes[expected["outcome"]],
        "observed_outcome": observed_outcome(value, last_tool),
        "fidelity_ok": fidelity_ok, "delivery_ok": delivery_ok,
        "answer_fidelity_ok": answer_fidelity_ok,
        "language_ok": language_ok,
        "tools_called": [part.tool_name for part in calls],
        "tool_args": args, "tool_return": content,
        "tool_sequence": [{"name": c.tool_name, "id": c.tool_call_id, "args": c.args_as_dict()} for c in calls],
        "request_id": value.get("request_id"),
        "questioned": questioned,
        "artifact_id": artifact.get("artifact_id") if isinstance(artifact, dict) else None,
    }


def annotate_turns(record: dict) -> None:
    """Attach the last data call's saved revision and request usage to each turn."""
    requests = {request["request_id"]: request for request in record.get("requests", [])}
    for turn in record["turns"]:
        request = requests.get(turn["request_id"], {})
        turn["revised"] = (request.get("revision") or {}).get("problem")
        turn["requests_used"] = request.get("requests_used")
        expected = turn["expected"]
        turn["revision_ok"] = ((turn["revised"] is not None) == expected["revision"]
                               if "revision" in expected else None)


def show_turn(name: str, index: int, turn: dict) -> None:
    redo = "" if turn["redo_ok"] is None else f" redo={turn['redo_ok']}"
    revision = "" if turn["revision_ok"] is None else f" revision={turn['revision_ok']}"
    error = f" error={turn['error']}" if turn.get("error") else ""
    print(f"{name} turn {index}: {turn['tool']} tool={turn['tool_ok']} "
          f"outcome={turn['outcome_ok']}{redo}{revision} revised={turn['revised']!r} "
          f"questioned={turn['questioned']} requests={turn['requests_used']}{error}", flush=True)


async def run_case(case: dict, lead, profiler, analyst, designer, designer_fallback=None,
                   evidence_dir: Path | None = None) -> dict:
    record = {"name": case["name"], "csv": case["csv"], "heldout": case.get("heldout", False), "turns": []}
    with tempfile.TemporaryDirectory(prefix="vis-lead-eval-") as directory:
        try:
            store = DatasetStore(Path(directory))
            requests = RequestStore(store)
            deps = AppDeps(store, profiler, analyst, designer, requests, designer_fallback=designer_fallback)
            csv = ROOT / case["csv"]
            brief = DataBrief.model_validate_json((ROOT / case["brief"]).read_bytes()) if case.get("brief") else None
            uploaded = store.save_upload(csv.name, csv.read_bytes(), brief)
            record["dataset_id"] = uploaded.dataset_id
            await profile_dataset(store, profiler, uploaded.dataset_id)
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            for expected in case["turns"]:
                turn = {**score_turn(expected, []), "expected": expected, "reply": None,
                        "tool_ok": False, "outcome_ok": False,
                        "redo_ok": False if "redo_analysis" in expected else None, "error": record["error"]}
                record["turns"].append(turn)
            annotate_turns(record)
            for index, turn in enumerate(record["turns"], 1):
                show_turn(case["name"], index, turn)
            return record
        history = []
        conversation_id = str(uuid4())
        for index, expected in enumerate(case["turns"], 1):
            started = perf_counter()
            prompt = expected["message"].replace("{dataset_id}", uploaded.dataset_id)
            reply, error, usage = None, None, None
            history_length = len(history)
            with capture_run_messages() as captured:
                try:
                    result = await lead.run(prompt, deps=deps, message_history=history,
                                            conversation_id=conversation_id)
                    history = result.all_messages()
                    reply = result.output
                    usage = to_jsonable_python(result.usage)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
            fresh = captured[history_length:]
            turn = {**score_turn(expected, fresh, reply), "expected": expected, "message": prompt, "reply": reply,
                    "seconds": perf_counter() - started,
                    "usage": usage,
                    "messages": json.loads(ModelMessagesTypeAdapter.dump_json(fresh))}
            if error:
                turn.update(error=error, outcome_ok=False)
            record["turns"].append(turn)
        # The temporary files disappear; retain the records and IDs for controller review.
        try:
            record["requests"] = [requests.get_request(item.request_id).model_dump(mode="json")
                                  for item in requests.list_requests(dataset_id=uploaded.dataset_id)]
            record["artifacts"] = [requests.get_artifact(item.artifact_id).model_dump(mode="json")
                                   for item in requests.list_artifacts(dataset_id=uploaded.dataset_id)]
            by_id = {artifact["artifact_id"]: artifact for artifact in record["artifacts"]}
            for turn in record["turns"]:
                if "analysis_reused" in turn["expected"]:
                    artifact = by_id.get(turn["artifact_id"], {})
                    parent = by_id.get(artifact.get("parent_artifact_id"), {})
                    left, right = artifact.get("report", {}), parent.get("report", {})
                    # A language-only revision changes report.language while reusing all saved SQL work.
                    same = bool(parent) and all(left.get(key) == right.get(key) for key in (
                        "analysis", "result", "created_at", "model", "seconds"))
                    turn["analysis_reuse_ok"] = bool(parent) and same == turn["expected"]["analysis_reused"]
            if evidence_dir is not None and (store.directory / "renders").exists():
                destination = evidence_dir / case["name"] / "renders"
                shutil.copytree(store.directory / "renders", destination, dirs_exist_ok=True)
                record["assets"] = [str(p.relative_to(evidence_dir)) for p in destination.rglob("*") if p.is_file()]
        except Exception as exc:  # one case's records must not abort the others
            record["records_error"] = f"{type(exc).__name__}: {exc}"
        annotate_turns(record)
        for index, turn in enumerate(record["turns"], 1):
            show_turn(case["name"], index, turn)
    return record


def summarize(results: list[dict]) -> dict:
    """Report repair decisions and indicator fidelity, including held-out cases separately."""
    turns = [turn for case in results for turn in case["turns"]]
    fidelity_keys = ("fidelity_ok", "delivery_ok", "answer_fidelity_ok", "analysis_reuse_ok", "language_ok")
    passed = [all(t["tool_ok"] and t["outcome_ok"]
                  and all(t.get(key) is not False for key in ("redo_ok", "revision_ok", *fidelity_keys))
                  for t in case["turns"]) for case in results]
    summary = {"cases": len(results), "cases_ok": sum(passed),
               "turns": len(turns), "tool_ok": sum(t["tool_ok"] for t in turns),
               "outcome_ok": sum(t["outcome_ok"] for t in turns),
               "redo_turns": sum(t["redo_ok"] is not None for t in turns),
               "redo_ok": sum(t["redo_ok"] is True for t in turns),
               "revision_turns": sum(t["revision_ok"] is not None for t in turns),
               "revision_ok": sum(t["revision_ok"] is True for t in turns),
               "revisions": sum(t["revised"] is not None for t in turns),
               "false_questions": sum(t["expected"]["outcome"] == "chart" and t["questioned"] for t in turns),
               "requests": sum(t["requests_used"] or 0 for t in turns),
               "heldout_cases": sum(bool(case.get("heldout")) for case in results),
               "heldout_cases_ok": sum(ok for case, ok in zip(results, passed) if case.get("heldout"))}
    for key in fidelity_keys:
        checked = [t[key] for t in turns if t.get(key) is not None]
        summary[key] = {"passed": sum(checked), "checked": len(checked)}
    summary["observed_outcomes"] = {name: sum(t.get("observed_outcome") == name for t in turns)
        for name in sorted({t["observed_outcome"] for t in turns if t.get("observed_outcome")})}
    print(f"cases {summary['cases_ok']}/{summary['cases']}, tool choice {summary['tool_ok']}/{summary['turns']}, "
          f"outcome {summary['outcome_ok']}/{summary['turns']}, "
          f"redo analysis {summary['redo_ok']}/{summary['redo_turns']}, "
          f"revision expected {summary['revision_ok']}/{summary['revision_turns']}, "
          f"revisions: {summary['revisions']}, false questions: {summary['false_questions']}, "
          f"requests: {summary['requests']}")
    print(f"held-out cases {summary['heldout_cases_ok']}/{summary['heldout_cases']}")
    checked_metrics = [f"{key} {summary[key]['passed']}/{summary[key]['checked']}"
                       for key in fidelity_keys if summary[key]["checked"]]
    if checked_metrics:
        print(", ".join(checked_metrics))
    return summary


def use_instructions(path: Path) -> str:
    """Run the lead with candidate instructions (an optimizer's output) instead of the source's, for this process."""
    text = path.read_text(encoding="utf-8")
    vis_agent.lead.LEAD_INSTRUCTIONS = text
    return text


async def evaluate(cases: list[dict], evidence_dir: Path | None = None) -> dict:
    profiler = create_profiler(os.getenv("PYDANTIC_AI_PROFILER_MODEL") or DEFAULT_PROFILER_MODEL)
    analyst = create_analyst(os.getenv("PYDANTIC_AI_ANALYST_MODEL") or DEFAULT_ANALYST_MODEL)
    designer = create_designer(os.getenv("PYDANTIC_AI_DESIGNER_MODEL") or DEFAULT_DESIGNER_MODEL)
    model = os.getenv("PYDANTIC_AI_MODEL") or DEFAULT_PROFILER_MODEL
    lead = create_lead(model, advisor_model="openrouter:openai/gpt-5.6-sol")
    # The runner retries a failed design once on this model, as the app does.
    designer_fallback = create_designer(os.getenv("PYDANTIC_AI_DESIGNER_FALLBACK_MODEL") or DEFAULT_FALLBACK_DESIGNER_MODEL)
    semaphore = asyncio.Semaphore(3)

    async def bounded(case):
        async with semaphore:
            return await run_case(case, lead, profiler, analyst, designer, designer_fallback, evidence_dir)

    results = await asyncio.gather(*(bounded(case) for case in cases))
    summary = summarize(results)
    return {"model": model, "summary": summary, "cases": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", action="store_true", help="Append ten corpus cases sampled with seed 11.")
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("cases.json"))
    parser.add_argument("--out", type=Path, default=Path("results.json"), help="Write results here (default: results.json).")
    parser.add_argument("--only", metavar="NAME", help="Run only this named case.")
    parser.add_argument("--instructions", type=Path, metavar="PATH",
                        help="Run the lead with these instructions instead of the source's (an optimizer's output).")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    cases = load_cases(args.cases)
    if args.corpus:
        cases += corpus_cases()
    if args.instructions:
        use_instructions(args.instructions)
    if args.only:
        cases = [case for case in cases if case["name"] == args.only]
        if not cases:
            parser.error(f"Unknown case: {args.only}")
    results = asyncio.run(evaluate(cases, args.out.parent / (args.out.stem + "-assets")))
    from evals.evidence import provenance
    results["provenance"] = provenance(args.cases, {"lead": results["model"],
        "analyst": os.getenv("PYDANTIC_AI_ANALYST_MODEL") or DEFAULT_ANALYST_MODEL,
        "designer": os.getenv("PYDANTIC_AI_DESIGNER_MODEL") or DEFAULT_DESIGNER_MODEL,
        "profiler": os.getenv("PYDANTIC_AI_PROFILER_MODEL") or DEFAULT_PROFILER_MODEL})
    results["provenance"]["prompts"]["lead"] = vis_agent.lead.LEAD_INSTRUCTIONS
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
