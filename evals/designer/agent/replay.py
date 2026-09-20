"""Isolate designer behavior by replaying identical saved lead inputs across models.

This is a diagnostic experiment, not a semantic or visual correctness score. It
records the exact input, source-preservation checks, full model messages and real
rendered artifacts. Run the end-to-end lead evaluation separately.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import statistics
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter

from dotenv import load_dotenv
from pydantic_ai import capture_run_messages
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai.models.wrapper import WrapperModel

from vis_agent.analyst.models import AnalysisReport, ResultColumn
from vis_agent.designer.agent import (
    build_prompt, create_designer, design_chart, instructions, render_design,
)
from vis_agent.designer.models import PreviousDesign
from vis_agent.designer.syntax import parse
from vis_agent.model_settings import text_specialist_settings
from vis_agent.models import DataBrief

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CASES = (
    "70ea08202f57d58f", "2177430e3e44a9a3", "f6687502449585a5",
    "45980b90faceca07", "c76808cc7a78dac8", "ae315d3da67a2d11",
)


class CountingModel(WrapperModel):
    """Count model invocations, including ones that never return a response.

    Captured ModelRequests alone are not outbound-call counts: Pydantic also
    records a terminal tool acknowledgement after successful deliver_design.
    This counter records framework model calls, not opaque provider/SDK retries.
    """

    def __init__(self, wrapped):
        super().__init__(wrapped)
        self.requests_started = 0

    async def request(self, messages, model_settings, model_request_parameters):
        self.requests_started += 1
        return await self.wrapped.request(messages, model_settings, model_request_parameters)

    @asynccontextmanager
    async def request_stream(self, messages, model_settings, model_request_parameters, run_context=None):
        self.requests_started += 1
        async with self.wrapped.request_stream(messages, model_settings, model_request_parameters, run_context) as stream:
            yield stream


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def replay_settings(model: str, routing: str) -> dict:
    """Per-run routing experiment; never mutate runtime/default model settings."""
    settings = text_specialist_settings(model)
    if routing == "latency":
        settings["openrouter_provider"] = {**settings.get("openrouter_provider", {}), "sort": "latency"}
    return settings


def model_turn_metrics(messages: list[dict]) -> dict:
    responses = [message for message in messages if message["kind"] == "response"]
    return {
        "model_request_messages": sum(message["kind"] == "request" for message in messages),
        "model_response_messages": len(responses),
        "downstream_providers": [(message.get("provider_details") or {}).get("downstream_provider")
                                 for message in responses],
    }


def replay_input(case: dict, guidance: str = "saved") -> dict:
    """Recover the first design request, not its eventually repaired final spec.

    Metadata comes from draw's pre-design table snapshot. Partial annotations are
    merged only for exact existing columns, without changing cells or SQL; this
    avoids reproducing an unrelated lead-tool rejection before designer dispatch.
    """
    request = next(item for item in case["requests"] if item.get("steps", {}).get("analyze"))
    report = AnalysisReport.model_validate(request["steps"]["analyze"])
    calls = [call for turn in case["turns"] for call in turn.get("tool_sequence", [])
             if call["name"] == "design_visualization"]
    if not calls:
        raise ValueError(f"{case['name']}: no recorded designer request")
    args = calls[0]["args"]
    for turn in case["turns"]:
        for message in turn.get("messages", []):
            for part in message.get("parts", []):
                content = part.get("content")
                if (part.get("tool_name") == "draw" and isinstance(content, dict)
                        and content.get("table", {}).get("columns")):
                    snapshot = content["table"]
                    fields = ResultColumn.model_fields
                    report.analysis.columns = [ResultColumn.model_validate({
                        key: value for key, value in column.items() if key in fields
                    }) for column in snapshot["columns"]]
                    break
    if args.get("columns"):
        annotations = [ResultColumn.model_validate(value) for value in args["columns"]]
        names = [column.name for column in annotations]
        if len(set(names)) != len(names) or set(names) - set(report.result.columns):
            raise ValueError(f"{case['name']}: invalid annotation identities")
        by_name = {column.name: column for column in annotations}
        report.analysis.columns = [by_name.get(column.name, column) for column in report.analysis.columns]
    brief = request.get("brief")
    direction = (args.get("direction") or report.question) if guidance == "saved" else report.question
    return {
        "name": case["name"], "report": report.model_dump(mode="json"), "brief": brief,
        "direction": direction, "required_columns": args.get("required_columns") or [],
        "guidance": guidance, "annotation_mode": "exact-name partial merge",
    }


async def run_one(inputs: dict, model: str, out: Path, semaphore: asyncio.Semaphore,
                  routing: str = "default") -> dict:
    async with semaphore:
        source = AnalysisReport.model_validate(inputs["report"])
        brief = DataBrief.model_validate(inputs["brief"]) if inputs["brief"] else None
        previous = PreviousDesign(spec=None, change=inputs["direction"])
        before = digest(source.model_dump(mode="json"))
        name = f"{inputs['name']}-{model.split(':', 1)[-1].replace('/', '-')}-{inputs['guidance']}-{routing}"
        directory = out.with_suffix("") / name
        designer = create_designer(model)
        counted_model = CountingModel(model)
        started = perf_counter()
        settings = replay_settings(model, routing)
        with capture_run_messages() as messages, designer.override(model=counted_model, model_settings=settings):
            result = await design_chart(source, designer, brief, previous=previous,
                                        required_columns=inputs["required_columns"])
        rendered = None
        render_error = None
        if result.design is not None:
            try:
                rendered = await asyncio.to_thread(render_design, source, result.design, directory)
            except Exception as exc:
                render_error = f"{type(exc).__name__}: {exc}"
        used = set()
        transforms = {}
        if result.design is not None:
            spec = parse(result.design.spec)
            used = set(source.result.columns) if spec.type == "table" else set(spec.bind.values()) | set(spec.fold)
            for card in spec.cards:
                used.update([card.value, *card.context, *card.support])
            transforms = {"fold": spec.fold, "percent": spec.percent, "limit": spec.limit}
        prompt = build_prompt(source, brief, previous=previous, required_columns=inputs["required_columns"])
        recorded_messages = json.loads(ModelMessagesTypeAdapter.dump_json(messages))
        record = {
            "case": inputs["name"], "model": model, "guidance": inputs["guidance"],
            "routing": routing, "model_settings": settings,
            "model_calls_started": counted_model.requests_started,
            "input_sha256": digest(inputs), "prompt_sha256": digest(prompt.model_dump(mode="json")),
            "result": result.model_dump(mode="json"),
            "source_unchanged": before == digest(source.model_dump(mode="json")),
            "bound_columns": sorted(used),
            "omitted_columns": [column for column in source.result.columns if column not in used],
            "missing_required_columns": [column for column in inputs["required_columns"] if column not in used],
            "transforms": transforms, "rendered": rendered.model_dump(mode="json") if rendered else None,
            "render_error": render_error, "total_seconds": perf_counter() - started,
            "messages": recorded_messages, **model_turn_metrics(recorded_messages),
        }
        status = "rendered" if rendered else "failed"
        print(f"{inputs['name']} {model} {inputs['guidance']}/{routing}: {status}, "
              f"design={result.seconds:.2f}s requests={result.requests} checks={result.check_calls}", flush=True)
        return record


def summarise(records: list[dict]) -> list[dict]:
    groups = {}
    for record in records:
        groups.setdefault((record["model"], record["guidance"], record.get("routing", "default")), []).append(record)
    return [{
        "model": model, "guidance": guidance, "routing": routing, "cases": len(rows),
        "designed": sum(row["result"]["design"] is not None for row in rows),
        "rendered": sum(row["rendered"] is not None for row in rows),
        "source_unchanged": sum(row["source_unchanged"] for row in rows),
        "required_columns_bound": sum(not row["missing_required_columns"] and row["rendered"] is not None for row in rows),
        "requests": sum(row["result"]["requests"] for row in rows),
        "model_calls_started": (sum(row["model_calls_started"] for row in rows)
                                if all("model_calls_started" in row for row in rows) else None),
        "model_request_messages": sum(row.get("model_request_messages", 0) for row in rows),
        "model_response_messages": sum(row.get("model_response_messages", 0) for row in rows),
        "mean_design_seconds": statistics.mean(row["result"]["seconds"] for row in rows),
        "median_design_seconds": statistics.median(row["result"]["seconds"] for row in rows),
        "max_design_seconds": max(row["result"]["seconds"] for row in rows),
        "semantic_and_visual_correctness": "not scored; inspect artifacts and source values independently",
    } for (model, guidance, routing), rows in groups.items()]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--guidance", action="append", choices=("saved", "intent"))
    parser.add_argument("--routing", action="append", choices=("default", "latency"))
    parser.add_argument("--concurrency", type=int, default=2, choices=(1, 2))
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.ERROR)
    source = json.loads(args.source.read_text(encoding="utf-8"))
    ids = args.case_id or DEFAULT_CASES
    inputs = [replay_input(case, guidance) for case in source["cases"]
              if any(case["name"].endswith(case_id) for case_id in ids)
              for guidance in args.guidance or ["saved"]]
    if len(inputs) != len(ids) * len(args.guidance or ["saved"]):
        raise ValueError("Requested replay case IDs were not uniquely found")
    semaphore = asyncio.Semaphore(args.concurrency)
    records = []
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tasks = [asyncio.create_task(run_one(value, model, args.out, semaphore, routing))
             for value in inputs for model in args.model for routing in args.routing or ["default"]]
    for future in asyncio.as_completed(tasks):
        records.append(await future)
        args.out.write_text(json.dumps({
            "source": str(args.source.resolve()), "instruction_sha256": digest(instructions()),
            "inputs": inputs, "summary": summarise(records), "records": records,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summarise(records), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
