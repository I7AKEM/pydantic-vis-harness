"""Terminal entry points: chat, profiling, questions, and saved check failures."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from vis_agent.analyst.agent import analyze_dataset
from vis_agent.models import DataBrief
from vis_agent.profiler.agent import profile_dataset


def resources():
    """Import the wired application lazily so tests and --help never touch the real data directory."""
    import vis_agent.app

    return vis_agent.app.agent, vis_agent.app.deps, vis_agent.app.store, vis_agent.app.profiler, vis_agent.app.analyst


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vis", description="Visualization agent, phase 2.")
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
    commands.add_parser("failures", help="List failed checks across saved profiles.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "chat":
        agent, deps, _store, _profiler, _analyst = resources()
        agent.to_cli_sync(deps=deps, prog_name="vis")
        return 0
    if args.command == "failures":
        _agent, _deps, store, _profiler, _analyst = resources()
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
    _agent, _deps, store, profiler, analyst = resources()
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
