"""Terminal entry points: an interactive chat with the lead, and one-shot profiling."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from profile_models import DataBrief
from profiler import profile_dataset


def resources():
    """Import the wired application lazily so tests and --help never touch the real data directory."""
    import main

    return main.agent, main.deps, main.store, main.profiler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vis", description="Visualization agent, phase 1.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("chat", help="Talk to the lead agent in the terminal.")
    profile = commands.add_parser("profile", help="Profile a dataset and print the profile as JSON.")
    profile.add_argument("dataset_id", nargs="?", help="An existing ds_ ID.")
    profile.add_argument("--upload", type=Path, help="A CSV file to upload first.")
    profile.add_argument("--brief", type=Path, help="A JSON file holding a data brief.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "chat":
        agent, deps, _store, _profiler = resources()
        agent.to_cli_sync(deps=deps, prog_name="vis")
        return 0
    if not args.dataset_id and not args.upload:
        parser.error("give a dataset_id or --upload a CSV file")
    _agent, _deps, store, profiler = resources()
    brief = DataBrief.model_validate_json(args.brief.read_text()) if args.brief else None
    dataset_id = args.dataset_id
    if args.upload:
        dataset_id = store.save_upload(args.upload.name, args.upload.read_bytes(), brief).dataset_id
        brief = None
    profile = asyncio.run(profile_dataset(store, profiler, dataset_id, brief=brief))
    print(json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
