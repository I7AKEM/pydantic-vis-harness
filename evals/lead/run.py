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
from vis_agent.designer.agent import DEFAULT_DESIGNER_MODEL, create_designer
from vis_agent.lead import create_lead
from vis_agent.models import DataBrief
from vis_agent.profiler.agent import DEFAULT_PROFILER_MODEL, create_profiler, profile_dataset
from vis_agent.requests.store import RequestStore
from vis_agent.store import DatasetStore

ROOT = Path(__file__).resolve().parents[2]
DATA_TOOLS = {"draw", "answer_question", "revise", "resume"}


def load_cases() -> list[dict]:
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
    call = next((part for part in calls if part.tool_name in DATA_TOOLS), None)
    returned = next((part for part in parts if isinstance(part, ToolReturnPart) and call is not None
                     and part.tool_call_id == call.tool_call_id and part.tool_name == call.tool_name), None)
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
    artifact = value.get("artifact")
    outcomes = {
        "artifact": artifact is not None,
        "question": value.get("clarification") is not None,
        "artifact_or_question": artifact is not None or value.get("clarification") is not None,
        # A corpus question over a result-table export may be drawn, asked about, or answered with a table.
        "answered": artifact is not None or value.get("clarification") is not None
        or (tool == "answer_question" and bool(value.get("rows"))),
        "table": tool == "answer_question" and bool(value.get("rows")),
        "text": call is None or (artifact is None and value.get("clarification") is None),
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
        "artifact_id": artifact.get("artifact_id") if isinstance(artifact, dict) else None,
    }


def show_turn(name: str, index: int, turn: dict) -> None:
    redo = "" if turn["redo_ok"] is None else f" redo={turn['redo_ok']}"
    error = f" error={turn['error']}" if turn.get("error") else ""
    print(f"{name} turn {index}: {turn['tool']} tool={turn['tool_ok']} "
          f"outcome={turn['outcome_ok']}{redo}{error}", flush=True)


async def run_case(case: dict, lead, profiler, analyst, designer) -> dict:
    record = {"name": case["name"], "csv": case["csv"], "turns": []}
    with tempfile.TemporaryDirectory(prefix="vis-lead-eval-") as directory:
        try:
            store = DatasetStore(Path(directory))
            requests = RequestStore(store)
            deps = AppDeps(store, profiler, analyst, designer, requests)
            csv = ROOT / case["csv"]
            brief = DataBrief.model_validate_json((ROOT / case["brief"]).read_bytes()) if case.get("brief") else None
            uploaded = store.save_upload(csv.name, csv.read_bytes(), brief)
            record["dataset_id"] = uploaded.dataset_id
            await profile_dataset(store, profiler, uploaded.dataset_id)
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            for index, expected in enumerate(case["turns"], 1):
                turn = {**score_turn(expected, []), "expected": expected, "reply": None,
                        "tool_ok": False, "outcome_ok": False,
                        "redo_ok": False if "redo_analysis" in expected else None, "error": record["error"]}
                record["turns"].append(turn)
                show_turn(case["name"], index, turn)
            return record
        history = []
        conversation_id = str(uuid4())
        for index, expected in enumerate(case["turns"], 1):
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
            show_turn(case["name"], index, turn)
        # The temporary files disappear; retain the records and IDs for controller review.
        try:
            record["requests"] = [requests.get_request(item.request_id).model_dump(mode="json")
                                  for item in requests.list_requests(dataset_id=uploaded.dataset_id)]
            record["artifacts"] = [item.model_dump(mode="json")
                                   for item in requests.list_artifacts(dataset_id=uploaded.dataset_id)]
        except Exception as exc:  # one case's records must not abort the others
            record["records_error"] = f"{type(exc).__name__}: {exc}"
    return record


async def evaluate(cases: list[dict]) -> dict:
    profiler = create_profiler(os.getenv("PYDANTIC_AI_PROFILER_MODEL") or DEFAULT_PROFILER_MODEL)
    analyst = create_analyst(os.getenv("PYDANTIC_AI_ANALYST_MODEL") or DEFAULT_ANALYST_MODEL)
    designer = create_designer(os.getenv("PYDANTIC_AI_DESIGNER_MODEL") or DEFAULT_DESIGNER_MODEL)
    model = os.getenv("PYDANTIC_AI_MODEL") or "openrouter:anthropic/claude-sonnet-4.6"
    lead = create_lead(model, advisor_model="openrouter:openai/gpt-5.6-sol")
    semaphore = asyncio.Semaphore(3)

    async def bounded(case):
        async with semaphore:
            return await run_case(case, lead, profiler, analyst, designer)

    results = await asyncio.gather(*(bounded(case) for case in cases))
    turns = [turn for case in results for turn in case["turns"]]
    summary = {"turns": len(turns), "tool_ok": sum(t["tool_ok"] for t in turns),
               "outcome_ok": sum(t["outcome_ok"] for t in turns),
               "redo_turns": sum(t["redo_ok"] is not None for t in turns),
               "redo_ok": sum(t["redo_ok"] is True for t in turns)}
    print(f"tool choice {summary['tool_ok']}/{summary['turns']}, "
          f"outcome {summary['outcome_ok']}/{summary['turns']}, "
          f"redo analysis {summary['redo_ok']}/{summary['redo_turns']}")
    return {"model": model, "summary": summary, "cases": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", action="store_true", help="Append ten corpus cases sampled with seed 11.")
    parser.add_argument("--out", type=Path, default=Path("results.json"), help="Write results here (default: results.json).")
    parser.add_argument("--only", metavar="NAME", help="Run only this named case.")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    cases = load_cases()
    if args.corpus:
        cases += corpus_cases()
    if args.only:
        cases = [case for case in cases if case["name"] == args.only]
        if not cases:
            parser.error(f"Unknown case: {args.only}")
    results = asyncio.run(evaluate(cases))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
