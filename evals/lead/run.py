"""Evaluate scripted lead conversations; run with --corpus for ten seed-11 corpus questions."""

import argparse
import asyncio
import json
import os
import random
import tempfile
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from pydantic_ai import capture_run_messages
from pydantic_ai.messages import ToolCallPart, ToolReturnPart

from evals.designer.agent.corpus_tools.select import CORPUS, read_manifest
from vis_agent.analyst.agent import DEFAULT_ANALYST_MODEL, create_analyst
from vis_agent.deps import AppDeps
from vis_agent.designer.agent import DEFAULT_DESIGNER_MODEL, DEFAULT_FALLBACK_DESIGNER_MODEL, create_designer
import vis_agent.lead
from vis_agent.lead import create_lead
from vis_agent.models import DataBrief
from vis_agent.profiler.agent import DEFAULT_PROFILER_MODEL, create_profiler, profile_dataset
from vis_agent.requests.store import RequestStore
from vis_agent.store import DatasetStore

ROOT = Path(__file__).resolve().parents[2]
DATA_TOOLS = {"draw", "answer_question", "revise", "resume"}


def load_cases() -> list[dict]:
    # Cases marked heldout are evaluation-only; exclude them from any future prompt tuning.
    return json.loads((Path(__file__).with_name("cases.json")).read_text(encoding="utf-8"))


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


def score_turn(expected: dict, messages: list) -> dict:
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
    }
    accepted = expected["tool"] if isinstance(expected["tool"], list) else [expected["tool"]]
    # redo_analysis is judged only when a revision was expected and made; a turn that accepts resume or
    # revise (an answer that may continue a question or change a delivered chart) judges it on revise alone.
    redo_ok = None
    if "redo_analysis" in expected and (tool == "revise" or not isinstance(expected["tool"], list)):
        redo_ok = tool == "revise" and args.get("redo_analysis") is expected["redo_analysis"]
    return {
        "tool": tool, "tool_ok": tool in accepted,
        "redo_ok": redo_ok,
        "outcome_ok": outcomes[expected["outcome"]],
        "tools_called": [part.tool_name for part in calls],
        "tool_args": args, "tool_return": content,
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


async def run_case(case: dict, lead, profiler, analyst, designer, designer_fallback=None) -> dict:
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
        for expected in case["turns"]:
            prompt = expected["message"].replace("{dataset_id}", uploaded.dataset_id)
            reply, error = None, None
            history_length = len(history)
            with capture_run_messages() as captured:
                try:
                    result = await lead.run(prompt, deps=deps, message_history=history,
                                            conversation_id=conversation_id)
                    history = result.all_messages()
                    reply = result.output
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
            turn = {**score_turn(expected, captured[history_length:]), "expected": expected, "message": prompt, "reply": reply}
            if error:
                turn.update(error=error, outcome_ok=False)
            record["turns"].append(turn)
        # The temporary files disappear; retain the records and IDs for controller review.
        try:
            record["requests"] = [requests.get_request(item.request_id).model_dump(mode="json")
                                  for item in requests.list_requests(dataset_id=uploaded.dataset_id)]
            record["artifacts"] = [item.model_dump(mode="json")
                                   for item in requests.list_artifacts(dataset_id=uploaded.dataset_id)]
        except Exception as exc:  # one case's records must not abort the others
            record["records_error"] = f"{type(exc).__name__}: {exc}"
        annotate_turns(record)
        for index, turn in enumerate(record["turns"], 1):
            show_turn(case["name"], index, turn)
    return record


def summarize(results: list[dict]) -> dict:
    """Print and return scores and repair counts, with held-out cases reported separately."""
    turns = [turn for case in results for turn in case["turns"]]
    passed = [all(t["tool_ok"] and t["outcome_ok"] for t in case["turns"]) for case in results]
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
    print(f"cases {summary['cases_ok']}/{summary['cases']}, tool choice {summary['tool_ok']}/{summary['turns']}, "
          f"outcome {summary['outcome_ok']}/{summary['turns']}, "
          f"redo analysis {summary['redo_ok']}/{summary['redo_turns']}, "
          f"revision expected {summary['revision_ok']}/{summary['revision_turns']}, "
          f"revisions: {summary['revisions']}, false questions: {summary['false_questions']}, "
          f"requests: {summary['requests']}")
    print(f"held-out cases {summary['heldout_cases_ok']}/{summary['heldout_cases']}")
    return summary


def use_instructions(path: Path) -> str:
    """Run the lead with candidate instructions (an optimizer's output) instead of the source's, for this process."""
    text = path.read_text(encoding="utf-8")
    vis_agent.lead.LEAD_INSTRUCTIONS = text
    return text


async def evaluate(cases: list[dict]) -> dict:
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
            return await run_case(case, lead, profiler, analyst, designer, designer_fallback)

    results = await asyncio.gather(*(bounded(case) for case in cases))
    summary = summarize(results)
    return {"model": model, "summary": summary, "cases": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", action="store_true", help="Append ten corpus cases sampled with seed 11.")
    parser.add_argument("--out", type=Path, default=Path("results.json"), help="Write results here (default: results.json).")
    parser.add_argument("--only", metavar="NAME", help="Run only this named case.")
    parser.add_argument("--instructions", type=Path, metavar="PATH",
                        help="Run the lead with these instructions instead of the source's (an optimizer's output).")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    cases = load_cases()
    if args.corpus:
        cases += corpus_cases()
    if args.instructions:
        use_instructions(args.instructions)
    if args.only:
        cases = [case for case in cases if case["name"] == args.only]
        if not cases:
            parser.error(f"Unknown case: {args.only}")
    results = asyncio.run(evaluate(cases))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
