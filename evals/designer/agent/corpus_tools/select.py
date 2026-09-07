"""Select coverage first, then a seeded shuffle; no models or network calls.

Run from the repository root: python -m evals.designer.agent.corpus_tools.select.
The English supplement reuses real Phase 4 reports, grouped by their original CSV.
"""

import argparse
import csv
import json
import random
import re
from collections import defaultdict
from pathlib import Path

import duckdb

from vis_agent.profiler.measurements import GEOMETRY_NAME, WKT_SQL_PATTERN
from vis_agent.store import quote_identifier

CORPUS = Path('/Users/muhammad/Documents/NACI/Insightor/insightor_POC/exports/visualization_csv_corpus_dev_2026-09-01_500')
EXCLUDED_PROFILER_SETS = [Path('evals/profiler/corpus_cases'), Path('evals/profiler/corpus_train')]
TASK_TO_INTENT = {'single_value': 'share', 'comparison': 'compare', 'ranking': 'rank',
                  'composition': 'composition', 'distribution': 'distribution'}
SCALE = Path('evals/designer/agent/scale')
PHASE4_CASES = Path('evals/designer/agent/cases.json')
ANALYST_CASES = Path('evals/analyst/cases/cases.json')
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # DatasetStore's default; never upload a larger file.
COVERAGE_KEYS = ('task', 'shape', 'rows_bucket', 'arabic_categories', 'temporal', 'nulls', 'negatives', 'long_text')
ARABIC_LETTERS = r'[ء-يٮ-ۓەۥۦۮۯۺ-ۼۿ]'
TIME_NAME = r'(^|[_\s])(date|datetime|timestamp|year|month|day|quarter|تاريخ|سنة|السنة|عام|العام|شهر|الشهر)($|[_\s])'
MAP_TYPES = {'map', 'choropleth', 'choropleth_map', 'scatter_map', 'bubble_map', 'geo', 'geographic'}


def read_manifest(path: Path) -> list[dict]:
    with path.open(encoding='utf-8') as source:
        return [json.loads(line) for line in source if line.strip()]


def _metadata(row: dict) -> dict:
    occurrence = (row.get('occurrences') or [{}])[0]
    visualizations = occurrence.get('visualizations') or [{}]
    return {'task': (occurrence.get('orchestrator_intent') or {}).get('task'),
            'requested_type': (occurrence.get('orchestrator_visual_requirements') or {}).get('requested_type'),
            'chosen_chart': visualizations[0].get('chart_type')}


def _map(row: dict) -> bool:
    # A later map occurrence still makes this a map dataset, though its question
    # and recorded metadata always come from the first occurrence.
    for occurrence in row.get('occurrences', []):
        types = [(occurrence.get('orchestrator_intent') or {}).get('task'),
                 (occurrence.get('orchestrator_visual_requirements') or {}).get('requested_type')]
        types += [v.get('chart_type') for v in occurrence.get('visualizations') or []]
        if any(str(value).lower() in MAP_TYPES for value in types):
            return True
    return False


def features(row: dict, csv_path: Path) -> dict:
    """Measure full columns inside DuckDB; return aggregates and labels, never cells."""
    if csv_path.stat().st_size > MAX_UPLOAD_BYTES:
        raise ValueError('CSV exceeds the upload limit')
    csv.field_size_limit(MAX_UPLOAD_BYTES)
    with csv_path.open(encoding='utf-8-sig', newline='') as source:
        reader = csv.reader(source, strict=True)
        headers = next(reader, [])
        if not headers or len(headers) > 100 or any(not name.strip() for name in headers):
            raise ValueError('Invalid CSV header')
        if len({name.casefold() for name in headers}) != len(headers):
            raise ValueError('Duplicate CSV headers')
        for record in reader:
            if len(record) != len(headers):
                raise ValueError('Irregular CSV row')
    profile = row.get('fingerprint', {}).get('data_profile') or {}
    temporal_columns = profile.get('temporal_columns') or []
    geometry_columns = profile.get('geometry_columns') or []
    with duckdb.connect(config={'threads': 1}) as connection:
        connection.execute("CREATE TABLE data AS SELECT * FROM read_csv(?, header=true, delim=',', "
                           "all_varchar=true, sample_size=-1, strict_mode=true, null_padding=false, parallel=false)",
                           [str(csv_path)])
        actual_rows = connection.execute('SELECT count(*) FROM data').fetchone()[0]
        rows = row.get('fingerprint', {}).get('parsed_row_count', actual_rows)
        if rows != actual_rows:
            raise ValueError('Manifest row count differs from the parsed CSV')
        measurements = []
        for name in headers:
            column = quote_identifier(name)
            # Non-null numeric coverage determines labels; geometry/WKT columns are
            # excluded from category features. All returned values are statistics.
            nonnull, numeric, dates, arabic, nulls, negatives, longest, wkt = connection.execute(
                f'SELECT count({column}), count(try_cast({column} AS DOUBLE)), '
                f"count(*) FILTER (WHERE regexp_matches({column}, '^\\d{{4}}[-/]\\d{{1,2}}[-/]\\d{{1,2}}') "
                f'AND try_cast({column} AS DATE) IS NOT NULL), '
                f'count(*) FILTER (WHERE regexp_matches({column}, ?)), '
                f'count(*) - count({column}), count(*) FILTER (WHERE try_cast({column} AS DOUBLE) < 0), '
                f'coalesce(max(length({column})), 0), '
                f"count(*) FILTER (WHERE regexp_matches({column}, ?, 'i')) FROM data",
                [ARABIC_LETTERS, WKT_SQL_PATTERN],
            ).fetchone()
            time_name = connection.execute("SELECT regexp_matches(?, ?, 'i')", [name, TIME_NAME]).fetchone()[0]
            geometry = bool(GEOMETRY_NAME.search(name) or name in geometry_columns or wkt)
            temporal = bool(name in temporal_columns or time_name or (nonnull and dates == nonnull))
            measurements.append({'label': bool(nonnull and numeric < nonnull and not geometry),
                                 'temporal': temporal and not geometry, 'geometry': geometry,
                                 'nonnull': nonnull, 'arabic': arabic, 'nulls': nulls,
                                 'negatives': negatives, 'longest': longest})
    temporal = any(m['temporal'] for m in measurements)
    if len(headers) == 1:
        shape = 'one_number' if rows == 1 else 'one_column'
    elif len(headers) == 2:
        shape = 'time_measure' if temporal else 'category_measure'
    elif len(headers) == 3 and len([m for m in measurements if m['label']]) == 2:
        shape = 'category_group_measure'
    else:
        shape = 'wide'  # Also covers three columns without two labels.
    bucket = next(label for upper, label in [(0, '0'), (1, '1'), (10, '2-10'), (50, '11-50'),
                                            (200, '51-200'), (1000, '201-1000'), (float('inf'), '1001+')]
                  if rows <= upper)
    return {'shape': shape, 'rows': rows, 'rows_bucket': bucket,
            'arabic_categories': any(m['label'] and m['arabic'] for m in measurements),
            'temporal': temporal, 'nulls': any(m['nulls'] for m in measurements),
            'negatives': any(m['negatives'] for m in measurements),
            'long_text': any(m['longest'] > 40 and not m['geometry'] for m in measurements),
            'geometry_only': any(m['geometry'] for m in measurements)
            and not any(not m['geometry'] and m['nonnull'] for m in measurements),
            **_metadata(row)}


def select(rows: list[dict], corpus: Path, count: int = 200, seed: int = 7,
           excluded: set[str] = frozenset()) -> list[dict]:
    if count < 0:
        raise ValueError('count must be nonnegative')
    eligible = []
    seen_ids = set()
    for row in sorted(rows, key=lambda item: item['dataset_id']):
        dataset_id = row['dataset_id']
        occurrence = (row.get('occurrences') or [{}])[0]
        question = occurrence.get('question')
        fingerprint = row.get('fingerprint') or {}
        if (dataset_id in excluded or dataset_id in seen_ids or not question or not question.strip()
                or _map(row) or fingerprint.get('parse_status', 'parsed') != 'parsed'
                or fingerprint.get('parse_error') or fingerprint.get('irregular_row_count', 0)):
            continue
        csv_path = (corpus / row['csv_path']).resolve()
        if not csv_path.is_relative_to(corpus.resolve()) or csv_path.suffix.lower() != '.csv':
            continue
        try:
            measured = features(row, csv_path)
        except (OSError, UnicodeError, csv.Error, ValueError, duckdb.Error):
            continue
        if measured['geometry_only']:
            continue
        seen_ids.add(dataset_id)
        eligible.append({'name': re.sub(r'[^a-z0-9]+', '-', dataset_id.lower()).strip('-'),
                         'dataset_id': dataset_id, 'csv': str(csv_path), 'question': question,
                         'language': 'ar' if re.search(ARABIC_LETTERS, question) else 'en',
                         'intent': TASK_TO_INTENT.get(measured['task']),
                         'metadata': _metadata(row), 'features': measured})
    chosen = []
    seen = {key: set() for key in COVERAGE_KEYS}
    while len(chosen) < count:
        added = False
        for key in COVERAGE_KEYS:
            candidate = next((case for case in eligible if case['features'][key] not in seen[key]), None)
            if candidate is None:
                continue
            candidate['features']['selection_reason'] = f'coverage:{key}={candidate["features"][key]}'
            chosen.append(candidate)
            eligible.remove(candidate)
            for feature in COVERAGE_KEYS:
                seen[feature].add(candidate['features'][feature])
            added = True
            if len(chosen) == count:
                break
        if not added:
            break
    random.Random(seed).shuffle(eligible)
    for case in eligible[:max(0, count - len(chosen))]:
        case['features']['selection_reason'] = f'seeded shuffle:{seed}'
        chosen.append(case)
    return chosen


def _sizes(count: int) -> list[int]:
    sizes = [count * weight // 5 for weight in (3, 1, 1)]
    order = sorted(range(3), key=lambda i: -(count * (3, 1, 1)[i] % 5))
    for i in order[:count - sum(sizes)]:
        sizes[i] += 1
    return sizes


def splits(selected: list[dict], seeded_names: list[str], seed: int = 7) -> dict[str, list[str]]:
    """60/20/20 by case, keeping shared source datasets together.

    Names alone describe independent seeded datasets. To group derivatives with a
    parent, also include their entries in selected with source_dataset_id (top
    level or features). Do not fabricate a parent relationship from a name.
    """
    entries = {case['name']: case for case in selected}
    if len(entries) != len(selected) or len(set(seeded_names)) != len(seeded_names):
        raise ValueError('Duplicate case names')
    for name in seeded_names:
        entries.setdefault(name, {'name': name, 'dataset_id': name, 'language': 'ar'})
    seeded = set(seeded_names) | {c['name'] for c in selected if c.get('seeded')}
    groups = defaultdict(list)
    for case in sorted(entries.values(), key=lambda c: c['name']):
        source = (case.get('source_dataset_id') or case.get('features', {}).get('source_dataset_id')
                  or case.get('metadata', {}).get('source_dataset_id')
                  or case.get('dataset_id') or case['name'])
        groups[source].append(case)
    strata = defaultdict(list)
    for group in groups.values():
        stratum = (any(c['name'] in seeded for c in group), group[0].get('language', 'ar'))
        strata[stratum].append(group)
    remaining = _sizes(len(entries))
    result = {key: [] for key in ('train', 'dev', 'heldout')}
    keys = list(result)
    rng = random.Random(seed)
    # Seeded groups first, then English; each stratum gets proportional targets.
    for stratum in sorted(strata, key=lambda key: (not key[0], key[1] != 'en')):
        groups_in_stratum = strata[stratum]
        rng.shuffle(groups_in_stratum)
        groups_in_stratum.sort(key=len, reverse=True)
        target = _sizes(sum(map(len, groups_in_stratum)))
        allocated = [0, 0, 0]
        for group in groups_in_stratum:
            candidates = [i for i in range(3) if remaining[i] >= len(group)]
            if not candidates:
                raise ValueError('Cannot preserve dataset groups within proportional split sizes')
            i = max(candidates, key=lambda i: (target[i] - allocated[i], remaining[i], -i))
            result[keys[i]].extend(c['name'] for c in group)
            allocated[i] += len(group)
            remaining[i] -= len(group)
    return {key: sorted(names) for key, names in result.items()}


def _phase4_english(rows: list[dict], corpus: Path) -> list[dict]:
    if not PHASE4_CASES.exists():
        return []
    analyst_cases = {c['name']: c for c in json.loads(ANALYST_CASES.read_text(encoding='utf-8'))}
    by_id = {row['dataset_id']: row for row in rows}
    extras = {'actual_fine_distribution': 'vizcsv-113cb217c6077a95',
              'orders_and_average_price_by_status': 'vizcsv-1d9cda665cf60239'}
    selected = []
    for case in json.loads(PHASE4_CASES.read_text(encoding='utf-8')):
        if case['language'] != 'en' or case['expect'] != 'design':
            continue
        report_path = PHASE4_CASES.parent / case['report']
        report = json.loads(report_path.read_text(encoding='utf-8'))
        source_id = (Path(analyst_cases[case['name']]['csv']).stem if case['name'] in analyst_cases
                     else extras[case['name']])
        if source_id not in by_id:
            continue  # A custom corpus need not contain the Phase 4 source files.
        row = by_id[source_id]
        source_csv = (corpus / row['csv_path']).resolve()
        measured = features(row, source_csv)
        measured.update(source='phase4', source_report=str(report_path),
                        selection_reason='existing real English Phase 4 report')
        selected.append({'name': case['name'], 'dataset_id': source_id, 'csv': str(source_csv),
                         'question': report['question'], 'language': 'en',
                         'intent': case['brief']['intent'], 'metadata': _metadata(row), 'features': measured})
    return selected


def coverage_table(selected: list[dict]) -> str:
    """Coverage counts are queries too; Python only formats their results."""
    with duckdb.connect() as connection:
        connection.execute('CREATE TABLE selection AS SELECT unnest(?::JSON[]) AS item',
                           [[json.dumps(case) for case in selected]])
        lines = ['| Feature | Value | Cases |', '| --- | --- | ---: |']
        for key in ('language', 'source', *COVERAGE_KEYS):
            path = '$.language' if key == 'language' else f'$.features.{key}'
            counts = connection.execute(
                "SELECT coalesce(json_extract_string(item, ?), ?), count(*) FROM selection GROUP BY 1 ORDER BY 1",
                [path, 'corpus' if key == 'source' else 'null'],
            ).fetchall()
            lines += [f'| {key} | {value} | {count} |' for value, count in counts]
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, default=200)
    parser.add_argument('--corpus', type=Path, default=CORPUS)
    args = parser.parse_args()
    if args.count < 1:
        parser.error('--count must be positive')
    rows = read_manifest(args.corpus / 'manifest.jsonl')
    excluded = {path.stem for directory in EXCLUDED_PROFILER_SETS for path in directory.glob('*.csv')}
    phase4 = _phase4_english(rows, args.corpus) if args.count >= 20 else []
    candidates = select(rows, args.corpus, count=len(rows), excluded=excluded)
    english_slots = min(args.count - len(phase4), max(0, 20 - len(phase4)))
    english = [case for case in candidates if case['language'] == 'en'][:english_slots]
    reserved = {case['name'] for case in english}
    ordinary = [case for case in candidates if case['name'] not in reserved]
    chosen = ordinary[:args.count - len(phase4) - len(english)] + english + phase4
    if len(chosen) != args.count:
        raise ValueError(f'Only {len(chosen)} eligible cases available for --count {args.count}')
    for case in english:
        case['features']['selection_reason'] = 'real English corpus question for language coverage'
    if args.count >= 20 and len(english) + len(phase4) < 20:
        raise ValueError('Cannot reach twenty real English questions without inventing cases')
    assignments = splits(chosen, [])
    SCALE.mkdir(parents=True, exist_ok=True)
    for filename, value in [('selected.json', chosen), ('splits.json', assignments)]:
        (SCALE / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(coverage_table(chosen))
    print('Splits: ' + ', '.join(f'{key}={len(names)}' for key, names in assignments.items()))


if __name__ == '__main__':
    main()
