"""Terminal entry points for datasets, questions, chart design, and rendering."""

import argparse
import asyncio
import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from typing import get_args

from pydantic import ValidationError

from vis_agent.analyst.agent import analyze_dataset
from vis_agent.analyst.models import AnalysisReport
from vis_agent.designer.agent import design_chart, render_design, render_id
from vis_agent.designer.check import check_spec
from vis_agent.designer.models import SpecCheck, SpecError, Violation
from vis_agent.designer.recommend import recommend_charts
from vis_agent.designer.resolve import ResolveError
from vis_agent.designer.syntax import parse, to_text
from vis_agent.models import DataBrief, Intent
from vis_agent.profiler.agent import profile_dataset
from vis_agent.render import gptvis
from vis_agent.render.base import RenderFailed, RendererUnavailable
from vis_agent.requests.models import Caller
from dataclasses import replace

from pydantic_ai.usage import UsageLimits

from vis_agent.requests.service import REQUEST_LIMIT, answer_request, create_request, run_request
from vis_agent.requests.store import ArtifactNotFound, RequestNotFound
from vis_agent.store import DatasetNotFound


def resources():
    """Import the wired application lazily so tests and --help never touch the real data directory."""
    import vis_agent.app

    team = vis_agent.app.default
    return (team.lead, team.deps, vis_agent.app.store,
            team.deps.profiler, team.deps.analyst, team.deps.designer)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vis", description="Visualization agent, phase 6.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("chat", help="Talk to the lead agent in the terminal.")
    profile = commands.add_parser("profile", help="Profile a dataset and print the profile as JSON.")
    profile.add_argument("dataset_id", nargs="?", help="An existing ds_ ID.")
    profile.add_argument("--upload", type=Path, help="A CSV file to upload first.")
    profile.add_argument("--brief", type=Path, help="A JSON file holding a data brief.")
    ask = commands.add_parser("ask", help="Answer a question about a dataset and print the report as JSON.")
    ask.add_argument("dataset_id", nargs="?", help="An existing ds_ ID.")
    ask.add_argument("question", help="The question to answer.")
    ask.add_argument("--upload", type=Path, help="A CSV file to upload first.")
    ask.add_argument("--brief", type=Path, help="A JSON file holding a data brief.")
    draw = commands.add_parser("draw", help="Draw a chart for a question and print the outcome as JSON.")
    draw.add_argument("dataset_id", nargs="?", help="An existing ds_ ID.")
    draw.add_argument("question", help="The question to answer with a chart.")
    draw.add_argument("--upload", type=Path, help="A CSV file to upload first.")
    draw.add_argument("--brief", type=Path, help="A JSON file holding a data brief.")
    revise = commands.add_parser("revise", help="Revise an artifact into a new linked version.")
    revise.add_argument("artifact_id", help="The art_ ID to change.")
    revise.add_argument("change", help="What must differ.")
    revise.add_argument("--redo-analysis", action="store_true", help="The data must change, not only the chart.")
    resume = commands.add_parser("resume", help="Continue a request, answering its question when one is given.")
    resume.add_argument("request_id", help="The rq_ ID.")
    resume.add_argument("--answer", help="The answer to the pending question.")
    requests = commands.add_parser("requests", help="List requests, newest first.")
    requests.add_argument("--dataset", help="Only this dataset.")
    artifacts = commands.add_parser("artifacts", help="List a dataset's artifacts, newest first.")
    artifacts.add_argument("dataset_id")
    suggest = commands.add_parser("suggest", help="Ask the lead for three to five questions worth asking.")
    suggest.add_argument("dataset_id")
    commands.add_parser("failures", help="List failed checks across saved profiles.")
    recommend = commands.add_parser("recommend", help="Rank chart candidates for an analysis report.")
    recommend.add_argument("report", type=Path)
    recommend.add_argument("--intent", choices=get_args(Intent))
    recommend.add_argument("--suggested", help="Preferred chart name or alias.")
    check = commands.add_parser("check", help="Check a chart spec; without a report, only parse it.")
    check.add_argument("spec", type=Path)
    check.add_argument("--report", type=Path)
    check.add_argument("--renderer", choices=["gptvis"], default="gptvis")
    render = commands.add_parser("render", help="Check a spec and write a PNG, HTML page, and configuration.")
    render.add_argument("spec", type=Path)
    render.add_argument("--report", type=Path, required=True)
    render.add_argument("--out", type=Path)
    render.add_argument("--renderer", choices=["gptvis"], default="gptvis")
    design = commands.add_parser("design", help="Design a chart for an analysis report and render it.")
    design.add_argument("report", type=Path)
    design.add_argument("--brief", type=Path)
    design.add_argument("--out", type=Path)
    design.add_argument("--no-render", action="store_true")
    design.add_argument("--renderer", choices=["gptvis"], default="gptvis")
    commands.add_parser("doctor", help="Check Node, the renderer package, and an Arabic smoke render.")
    return parser


def _print_json(value) -> None:
    print(json.dumps(value.model_dump(mode="json") if hasattr(value, "model_dump") else value,
                     ensure_ascii=False, indent=2))


def _load_report(data: bytes) -> AnalysisReport:
    report = AnalysisReport.model_validate_json(data)
    if report.analysis is None or report.result is None:
        raise ValueError("The report needs an analysis and a result; resolve any clarification with the analyst first.")
    return report


def recommend_command(args: argparse.Namespace) -> int:
    report = _load_report(args.report.read_bytes())
    _print_json(recommend_charts(report.analysis.columns, report.result, args.intent, args.suggested))
    return 0


def check_command(args: argparse.Namespace) -> int:
    text = args.spec.read_text(encoding="utf-8")
    if args.report:
        report = _load_report(args.report.read_bytes())
        _print_json(check_spec(text, report.analysis.columns, report.result, args.renderer))
    else:
        try:
            check = SpecCheck(ok=True, canonical=to_text(parse(text)))
        except SpecError as error:
            check = SpecCheck(ok=False, violations=[
                Violation(rule="syntax", message=issue.message, line=issue.line,
                          fix="Correct the syntax on this line") for issue in error.issues
            ])
        _print_json({**check.model_dump(mode="json"),
                     "note": "Parse only: all other rules and renderer capability checks were skipped; supply --report for a full check."})
    return 0


def render_command(args: argparse.Namespace) -> int:
    text = args.spec.read_text(encoding="utf-8")
    report_bytes = args.report.read_bytes()
    report = _load_report(report_bytes)
    check = check_spec(text, report.analysis.columns, report.result, args.renderer)
    if not check.ok:
        _print_json(check)
        return 2
    out = args.out
    if out is None:
        digest = sha256(text.encode("utf-8") + report_bytes).hexdigest()[:12]
        out = resources()[2].directory / "renders" / digest
    _print_json(gptvis.render(parse(text), report.analysis.columns, report.result, out, compromises=check.compromises))
    return 0


def doctor_command(args: argparse.Namespace) -> int:
    try:
        node = subprocess.run(["node", "--version"], capture_output=True, text=True, check=True, timeout=5)
        version = node.stdout.strip()
    except (OSError, subprocess.SubprocessError) as error:
        version = f"unavailable ({error})"
    reason = gptvis.available()
    smoke = gptvis.smoke_test()
    print(f"Node: {version}")
    print(f"available: {reason or 'ok'}")
    print(f"smoke_test: {smoke or 'ok'}")
    return 1 if reason or smoke else 0


def design_command(args: argparse.Namespace) -> int:
    report = _load_report(args.report.read_bytes())
    brief = DataBrief.model_validate_json(args.brief.read_bytes()) if args.brief else None
    designer = resources()[5]
    design_report = asyncio.run(design_chart(report, designer, brief, args.renderer))
    rendered = None
    if design_report.design is not None and not args.no_render:
        out = args.out
        if out is None:
            out = resources()[2].directory / "renders" / render_id(design_report.design.spec, report)
        rendered = render_design(report, design_report.design, out, args.renderer)
    _print_json({**design_report.model_dump(mode="json"),
                 "render": rendered.model_dump(mode="json") if rendered is not None else None})
    return 0


SUGGEST_PROMPT = ("Suggest three to five questions worth asking about dataset {dataset_id}, each with a reason, "
                  "using only columns that exist in its profile. Do not draw anything.")
TERMINAL = Caller(kind="terminal")


def _exit_code(outcome) -> int:
    return {"done": 0, "waiting": 3}.get(outcome.status, 1)


def draw_command(args: argparse.Namespace) -> int:
    _agent, deps, store, *_ = resources()
    if not args.dataset_id and not args.upload:
        raise ValueError("give a dataset_id or --upload a CSV file")
    brief = DataBrief.model_validate_json(args.brief.read_text()) if args.brief else None
    dataset_id = args.dataset_id
    if args.upload:
        dataset_id = store.save_upload(args.upload.name, args.upload.read_bytes(), brief).dataset_id
    request = create_request(deps, type="new", dataset_id=dataset_id, question=args.question, caller=TERMINAL)
    outcome = asyncio.run(run_request(deps, request.request_id))
    _print_json(outcome)
    return _exit_code(outcome)


def revise_command(args: argparse.Namespace) -> int:
    _agent, deps, *_ = resources()
    dataset_id = deps.requests.get_artifact(args.artifact_id).dataset_id
    request = create_request(deps, type="revise", dataset_id=dataset_id, question=args.change, caller=TERMINAL,
                             parent_artifact_id=args.artifact_id, redo_analysis=args.redo_analysis)
    outcome = asyncio.run(run_request(deps, request.request_id))
    _print_json(outcome)
    return _exit_code(outcome)


def resume_command(args: argparse.Namespace) -> int:
    _agent, deps, *_ = resources()
    if args.answer:
        outcome = asyncio.run(answer_request(deps, args.request_id, args.answer, "terminal"))
    else:
        outcome = asyncio.run(run_request(deps, args.request_id))
    _print_json(outcome)
    return _exit_code(outcome)


def requests_command(args: argparse.Namespace) -> int:
    _agent, deps, *_ = resources()
    _print_json([s.model_dump(mode="json") for s in deps.requests.list_requests(dataset_id=args.dataset)])
    return 0


def artifacts_command(args: argparse.Namespace) -> int:
    _agent, deps, *_ = resources()
    _print_json([s.model_dump(mode="json") for s in deps.requests.list_artifacts(dataset_id=args.dataset_id)])
    return 0


def suggest_command(args: argparse.Namespace) -> int:
    agent, deps, *_ = resources()
    result = asyncio.run(agent.run(SUGGEST_PROMPT.format(dataset_id=args.dataset_id), deps=replace(deps, caller_kind="terminal"),
                                   usage_limits=UsageLimits(request_limit=REQUEST_LIMIT)))
    print(result.output)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    chart_commands = {"recommend": recommend_command, "check": check_command,
                      "render": render_command, "design": design_command, "doctor": doctor_command}
    if args.command in chart_commands:
        try:
            return chart_commands[args.command](args)
        except (RendererUnavailable, RenderFailed) as error:
            _print_json({"error": str(error)})
            return 1
        except (OSError, ValidationError, ValueError, ResolveError) as error:
            _print_json({"error": str(error)})
            return 2
    request_commands = {"draw": draw_command, "revise": revise_command, "resume": resume_command,
                        "requests": requests_command, "artifacts": artifacts_command, "suggest": suggest_command}
    if args.command in request_commands:
        try:
            return request_commands[args.command](args)
        except (DatasetNotFound, RequestNotFound, ArtifactNotFound, OSError, ValidationError, ValueError) as error:
            _print_json({"error": str(error)})
            return 2
    if args.command == "chat":
        agent, deps, _store, _profiler, _analyst, _designer = resources()
        agent.to_cli_sync(deps=replace(deps, caller_kind="terminal"), prog_name="vis")
        return 0
    if args.command == "failures":
        _agent, _deps, store, _profiler, _analyst, _designer = resources()
        grouped = {}
        for dataset_id, check, severity, message in store.failed_checks():
            grouped.setdefault(check, []).append((dataset_id, severity, message))
        for check, examples in grouped.items():
            count, severity = len(examples), examples[0][1]
            print(f"{count:>4}  {check}  ({severity})")
            for dataset_id, _severity, message in examples[:3]:
                print(f"      {dataset_id}: {message}")
        return 0
    if not args.dataset_id and not args.upload:
        parser.error("give a dataset_id or --upload a CSV file")
    _agent, _deps, store, profiler, analyst, _designer = resources()
    brief = DataBrief.model_validate_json(args.brief.read_text()) if args.brief else None
    dataset_id = args.dataset_id
    if args.upload:
        dataset_id = store.save_upload(args.upload.name, args.upload.read_bytes(), brief).dataset_id
        brief = None
    if args.command == "ask":
        report = asyncio.run(analyze_dataset(store, profiler, analyst, dataset_id, args.question, brief=brief))
    else:
        report = asyncio.run(profile_dataset(store, profiler, dataset_id, brief=brief))
    print(json.dumps(report.model_dump(mode="json") if hasattr(report, "model_dump") else report,
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
