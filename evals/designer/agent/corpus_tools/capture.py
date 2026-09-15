"""Capture fixed analyst inputs (controller only; requires OPENROUTER_API_KEY).

Run from the repository root. Existing valid reports are reused. --only captures a
subset, then builds cases from all available reports and records pending names in
decisions.json. Delete a report explicitly to recapture it. Phase 4 inputs are
always copied from their frozen reports, without another model call.
"""

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from vis_agent.analyst.agent import DEFAULT_ANALYST_MODEL, analyze_dataset, create_analyst
from vis_agent.analyst.models import AnalysisReport
from vis_agent.models import DataBrief
from vis_agent.profiler.agent import DEFAULT_PROFILER_MODEL, create_profiler
from vis_agent.store import DatasetStore

SCALE = Path('evals/designer/agent/scale')
PROVENANCE = (
    'Coverage-first selection from the read-only Insightor dev export, followed by a shuffle with seed 7. '
    'Fresh corpus cases exclude profiler corpus_cases/corpus_train, maps, invalid or oversized CSVs, and '
    'geometry-only results, and use the first occurrence question. Available real English Phase 4 cases '
    'are explicit reuse exceptions; eligible English corpus questions fill the remaining language quota. '
    'The synthetic Phase 4 empty_result is not imported. Shared source datasets stay '
    'in one split. Seeded derivatives are marked separately and retain their transformation metadata. '
    'Insightor chosen_chart and requested_type are provenance only, never acceptable-chart labels or '
    'designer suggestions. charts is null: the evaluation runner computes its rule-based reference. '
    'Corpus intents use TASK_TO_INTENT; reused Phase 4 intents retain the authored case intent. '
    'Capture uses the default profiler and analyst, up to three analysis attempts, with no designer call.'
)


def _read(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def _membership(path: Path) -> dict[str, str]:
    membership = {}
    for split, names in _read(path).items():
        if split not in {'train', 'dev', 'heldout'}:
            raise ValueError(f'Unknown split: {split}')
        for name in names:
            if name in membership:
                raise ValueError(f'Duplicate split membership: {name}')
            membership[name] = split
    return membership


def build_cases(selected: list[dict], seeded: list[dict], reports_dir: Path) -> list[dict]:
    membership = _membership(reports_dir.parent / 'splits.json')
    cases = []
    names = set()
    for is_seeded, entries in [(False, selected), (True, seeded)]:
        for entry in entries:
            name = entry['name']
            if name in names:
                raise ValueError(f'Duplicate case name: {name}')
            names.add(name)
            report_path = reports_dir / f'{name}.json'
            report = AnalysisReport.model_validate_json(report_path.read_text(encoding='utf-8'))
            if name not in membership:
                raise ValueError(f'No split assigned to {name}')
            languages = {'Arabic': 'ar', 'English': 'en', 'ar': 'ar', 'en': 'en'}
            if report.language not in languages:
                raise ValueError(f'Unsupported report language for {name}: {report.language}')
            intent = entry.get('intent', (entry.get('brief') or {}).get('intent'))
            cases.append({'name': name, 'report': f'{reports_dir.name}/{name}.json',
                          'brief': {'intent': intent, 'suggested_chart_type': None, 'brand_colors': []},
                          'expect': 'clarification' if is_seeded and entry.get('expect') == 'clarification' else 'design',
                          'charts': None, 'language': languages[report.language], 'bind': {}, 'emphasis': None,
                          'seeded': is_seeded, 'split': membership[name], 'metadata': entry.get('metadata', {}),
                          'why': entry.get('features', {}).get('selection_reason', 'Seeded edge case' if is_seeded else 'Corpus coverage')})
    return cases


def _csv_path(entry: dict) -> Path:
    path = Path(entry['csv'])
    # Selected CSVs are absolute. Seed manifests may use repository-relative,
    # scale-relative, or seeded-directory-relative paths.
    for candidate in (path, SCALE / path, SCALE / 'seeded' / path):
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(path)


async def _capture(entries: list[dict], reports_dir: Path, concurrency: int) -> dict[str, str]:
    if concurrency < 1:
        raise ValueError('concurrency must be positive')
    reports_dir.mkdir(parents=True, exist_ok=True)
    failures = {}
    pending = []
    for entry in entries:
        path = reports_dir / f'{entry["name"]}.json'
        if path.exists():
            AnalysisReport.model_validate_json(path.read_text(encoding='utf-8'))
        elif entry.get('features', {}).get('source') == 'phase4':
            source = Path(entry['features']['source_report'])
            frozen = source.read_text(encoding='utf-8')
            AnalysisReport.model_validate_json(frozen)
            # Validate compatibility, then preserve the original evidence exactly. New optional
            # model defaults must not silently rewrite an already frozen baseline report.
            path.write_text(frozen, encoding='utf-8')
        else:
            pending.append(entry)
    if not pending:
        return failures
    profiler = create_profiler(DEFAULT_PROFILER_MODEL)
    analyst = create_analyst(DEFAULT_ANALYST_MODEL)
    limit = asyncio.Semaphore(concurrency)
    with tempfile.TemporaryDirectory(prefix='vis-scale-capture-') as directory:
        store = DatasetStore(Path(directory))

        async def one(entry: dict) -> None:
            name = entry['name']
            async with limit:
                try:
                    csv_path = _csv_path(entry)
                    # Only an explicitly supplied data brief belongs in profiling;
                    # orchestrator visualization metadata never enters a model brief.
                    data_brief = entry.get('data_brief')
                    brief = DataBrief.model_validate(data_brief) if data_brief else None
                    source = await asyncio.to_thread(store.save_upload, csv_path.name, csv_path.read_bytes(), brief)
                    report = None
                    for attempt in range(3):
                        try:
                            report = await analyze_dataset(store, profiler, analyst, source.dataset_id, entry['question'])
                        except Exception:
                            if attempt == 2:
                                raise
                            continue
                        if report.analysis is not None and report.result is not None:
                            break
                        if entry.get('expect') == 'clarification' and report.clarification is not None:
                            break
                    _write(reports_dir / f'{name}.json', report.model_dump(mode='json'))
                    print(f'{name}: captured ({"table" if report.result is not None else "no table"})', flush=True)
                except Exception as exc:
                    failures[name] = f'{type(exc).__name__}: {exc}'
                    print(f'{name}: capture failed: {failures[name]}', flush=True)

        await asyncio.gather(*(one(entry) for entry in pending))
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', nargs='+', metavar='NAME')
    parser.add_argument('--concurrency', type=int, default=4)
    args = parser.parse_args()
    if args.concurrency < 1:
        parser.error('--concurrency must be positive')
    selected = _read(SCALE / 'selected.json')
    seeded = _read(SCALE / 'seeded/seeded.json')
    all_entries = selected + seeded
    membership = _membership(SCALE / 'splits.json')
    names = {entry['name'] for entry in all_entries}
    if len(names) != len(all_entries):
        parser.error('Duplicate selected/seeded names')
    if names != set(membership):
        parser.error('Regenerate splits with all selected and seeded entries before capture')
    if args.only and not set(args.only) <= names:
        parser.error('Unknown --only names: ' + ', '.join(sorted(set(args.only) - names)))
    entries = [entry for entry in all_entries if not args.only or entry['name'] in args.only]
    load_dotenv()
    failures = asyncio.run(_capture(entries, SCALE / 'reports', args.concurrency))
    available = {entry['name'] for entry in all_entries if (SCALE / 'reports' / f'{entry["name"]}.json').exists()}
    cases = build_cases([entry for entry in selected if entry['name'] in available],
                        [entry for entry in seeded if entry['name'] in available], SCALE / 'reports')
    _write(SCALE / 'cases.json', cases)
    seeded_names = {entry['name'] for entry in seeded}
    _write(SCALE / 'decisions.json', {
        'provenance': PROVENANCE, 'pending': sorted(names - available), 'failures': failures,
        'cases': [{**entry, 'seeded': entry['name'] in seeded_names, 'split': membership[entry['name']],
                   'report_status': 'captured' if entry['name'] in available else 'pending'} for entry in all_entries],
    })
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
