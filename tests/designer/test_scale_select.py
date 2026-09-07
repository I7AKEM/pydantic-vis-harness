import asyncio
import json
from pathlib import Path

import pytest

from evals.designer.agent.corpus_tools import capture
from evals.designer.agent.corpus_tools import select as selection


def manifest_row(tmp_path, name, content='category,value\nA,1\nB,2\n', task='comparison', **changes):
    path = tmp_path / f'{name}.csv'
    path.write_text(content, encoding='utf-8')
    row = {
        'dataset_id': name, 'csv_path': path.name,
        'fingerprint': {'parse_status': 'parsed', 'parsed_row_count': len(content.splitlines()) - 1,
                        'data_profile': {}},
        'occurrences': [{'question': 'Compare the values', 'orchestrator_intent': {'task': task},
                         'orchestrator_visual_requirements': {'requested_type': 'bar'},
                         'visualizations': [{'chart_type': 'pie'}]}],
    }
    row.update(changes)
    return row


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def test_manifest_selection_eligibility_and_determinism(tmp_path):
    rows = [manifest_row(tmp_path, f'good-{i}', task=task)
            for i, task in enumerate(['comparison', 'ranking', 'composition'])]
    rows += [manifest_row(tmp_path, 'map', task='map'),
             manifest_row(tmp_path, 'geometry', 'geometry\nPOINT(1 2)\n'),
             manifest_row(tmp_path, 'excluded'), manifest_row(tmp_path, 'large'),
             manifest_row(tmp_path, 'no-question', occurrences=[{'question': ' '}])]
    with (tmp_path / 'large.csv').open('ab') as file:
        file.truncate(selection.MAX_UPLOAD_BYTES + 1)
    manifest = tmp_path / 'manifest.jsonl'
    manifest.write_text('\n'.join(json.dumps(row) for row in rows))
    loaded = selection.read_manifest(manifest)
    picked = selection.select(loaded, tmp_path, excluded={'excluded'})
    assert {case['dataset_id'] for case in picked} == {'good-0', 'good-1', 'good-2'}
    assert picked == selection.select(list(reversed(loaded)), tmp_path, excluded={'excluded'})
    assert all(set(selection.COVERAGE_KEYS) <= case['features'].keys() for case in picked)
    assert picked[0]['metadata'] == {'task': 'comparison', 'requested_type': 'bar', 'chosen_chart': 'pie'}
    assert picked[0]['intent'] == 'compare'


def test_round_robin_covers_tasks_and_shapes_before_fill(tmp_path):
    contents = ['value\n1\n', 'value\n1\n2\n', 'category,value\nA,1\nB,2\n',
                'date,value\n2024-01-01,1\n2024-02-01,2\n',
                'category,group,value\nA,X,1\nB,Y,2\n', 'a,b,c,d\nA,1,2,3\n']
    tasks = ['single_value', 'distribution', 'comparison', 'ranking', 'composition', 'table']
    rows = [manifest_row(tmp_path, f'{i:02}-{j}', content, task)
            for i, (content, task) in enumerate(zip(contents, tasks)) for j in range(5)]
    picked = selection.select(rows, tmp_path, count=30)
    assert len({case['features']['task'] for case in picked[:6]}) == 6
    assert len({case['features']['shape'] for case in picked[:6]}) == 6
    assert picked != selection.select(rows, tmp_path, count=30, seed=8)


@pytest.mark.parametrize(('task', 'intent'), [
    ('single_value', 'share'), ('comparison', 'compare'), ('ranking', 'rank'),
    ('composition', 'composition'), ('distribution', 'distribution'), ('table', None), ('map', None),
])
def test_task_to_intent(task, intent):
    assert selection.TASK_TO_INTENT.get(task) == intent


def test_features_are_measured_from_csv(tmp_path):
    row = manifest_row(tmp_path, 'measured', 'category,value\nالرياض,-2\n' + 'س' * 41 + ',\n')
    row['occurrences'][0]['question'] = 'قارن القيم'
    picked = selection.select([row], tmp_path)[0]
    assert picked['language'] == 'ar'
    assert picked['features']['arabic_categories']
    assert picked['features']['nulls']
    assert picked['features']['negatives']
    assert picked['features']['long_text']
    assert picked['features']['rows_bucket'] == '2-10'


def test_bad_csv_and_any_map_occurrence_excluded(tmp_path):
    bad = manifest_row(tmp_path, 'bad', 'a,b\n1,2,3\n')
    mapped = manifest_row(tmp_path, 'mapped')
    mapped['occurrences'].append({'visualizations': [{'chart_type': 'choropleth'}]})
    wkt = manifest_row(tmp_path, 'wkt', 'payload\nPOINT(1 2)\n')
    assert selection.select([bad, mapped, wkt], tmp_path) == []


def test_first_occurrence_is_not_replaced_by_later_question(tmp_path):
    row = manifest_row(tmp_path, 'missing', occurrences=[{'question': None}, {'question': 'Later'}])
    assert selection.select([row], tmp_path) == []


@pytest.mark.parametrize(('count', 'sizes'), [(200, [120, 40, 40]), (10, [6, 2, 2]), (1, [1, 0, 0])])
def test_splits_proportional_disjoint_deterministic(count, sizes):
    cases = [{'name': f'case-{i}', 'dataset_id': f'dataset-{i}', 'language': 'ar' if i % 5 else 'en'}
             for i in range(count)]
    result = selection.splits(cases, [])
    assert [len(result[key]) for key in ['train', 'dev', 'heldout']] == sizes
    assert len(set(name for names in result.values() for name in names)) == count
    assert result == selection.splits(list(reversed(cases)), [])


def test_splits_spread_seeded_and_keep_shared_datasets_together():
    cases = [{'name': f'case-{i}', 'dataset_id': f'dataset-{i // 2}', 'language': 'ar'} for i in range(20)]
    seeded = [f'seed-{i}' for i in range(10)]
    result = selection.splits(cases, seeded)
    assert [len(names) for names in result.values()] == [18, 6, 6]
    assert all(set(names) & set(seeded) for names in result.values())
    membership = {name: split for split, names in result.items() for name in names}
    assert all(membership[f'case-{i}'] == membership[f'case-{i + 1}'] for i in range(0, 20, 2))


def test_splits_seeded_entries_can_supply_source_dataset():
    cases = [{'name': f'case-{i}', 'dataset_id': f'dataset-{i}', 'language': 'ar'} for i in range(20)]
    cases += [{'name': 'seed-related', 'dataset_id': 'derived', 'source_dataset_id': 'dataset-1',
               'seeded': True, 'language': 'ar'}]
    result = selection.splits(cases, ['seed-related'])
    membership = {name: split for split, names in result.items() for name in names}
    assert membership['seed-related'] == membership['case-1']
    assert len(membership) == 21


def report_fixture():
    return json.loads(Path('evals/designer/agent/reports/deaths_by_gender.json').read_text())


def test_build_cases_contract_and_missing_report(tmp_path):
    reports = tmp_path / 'reports'
    selected = [{'name': 'real', 'intent': 'compare', 'metadata': {'chosen_chart': 'pie'}, 'features': {}}]
    seeded = [{'name': 'seed', 'intent': 'trend', 'expect': 'clarification',
               'metadata': {'transformation': 'Hijri'}, 'features': {}}]
    write_json(tmp_path / 'splits.json', {'train': ['real'], 'dev': ['seed'], 'heldout': []})
    for name in ['real', 'seed']:
        write_json(reports / f'{name}.json', report_fixture())
    cases = capture.build_cases(selected, seeded, reports)
    for case, source in zip(cases, selected + seeded):
        assert case['charts'] is None and case['bind'] == {} and case['emphasis'] is None
        assert case['brief']['intent'] == source['intent']
        assert case['metadata'] == source['metadata']
        assert case['language'] == 'en'
    assert cases[0]['seeded'] is False and cases[0]['split'] == 'train'
    assert cases[1]['seeded'] is True and cases[1]['split'] == 'dev'
    assert cases[1]['expect'] == 'clarification'
    (reports / 'seed.json').unlink()
    with pytest.raises(FileNotFoundError):
        capture.build_cases(selected, seeded, reports)


def test_build_cases_rejects_invalid_report_and_missing_split(tmp_path):
    write_json(tmp_path / 'reports/real.json', {'not': 'a report'})
    write_json(tmp_path / 'splits.json', {'train': ['real'], 'dev': [], 'heldout': []})
    with pytest.raises(ValueError):
        capture.build_cases([{'name': 'real'}], [], tmp_path / 'reports')
    write_json(tmp_path / 'reports/real.json', report_fixture())
    write_json(tmp_path / 'splits.json', {'train': [], 'dev': [], 'heldout': []})
    with pytest.raises(ValueError, match='split'):
        capture.build_cases([{'name': 'real'}], [], tmp_path / 'reports')


@pytest.mark.parametrize(('count', 'sizes'), [(3, [2, 1, 0]), (10, [6, 2, 2]), (25, [15, 5, 5])])
def test_select_main_writes_both_outputs(tmp_path, monkeypatch, count, sizes):
    rows = [manifest_row(tmp_path, f'real-{i}') for i in range(30)]
    (tmp_path / 'manifest.jsonl').write_text('\n'.join(json.dumps(row) for row in rows))
    monkeypatch.setattr(selection, 'CORPUS', tmp_path)
    monkeypatch.setattr(selection, 'SCALE', tmp_path / 'scale')
    monkeypatch.setattr(selection, 'PHASE4_CASES', tmp_path / 'no-phase4.json')
    monkeypatch.setattr('sys.argv', ['select', '--count', str(count)])
    selection.main()
    selected = json.loads((tmp_path / 'scale/selected.json').read_text())
    assert len(selected) == count
    assert [len(names) for names in json.loads((tmp_path / 'scale/splits.json').read_text()).values()] == sizes


def test_phase4_real_english_imports_preserve_questions_and_source_ids():
    cases = json.loads(Path('evals/designer/agent/scale/selected.json').read_text())
    imported = [case for case in cases if case['features'].get('source') == 'phase4']
    assert len(cases) == 200 and len(imported) == 16
    assert len([case for case in cases if case['language'] == 'en']) == 20
    assert all(case['name'] != 'empty_result' for case in imported)
    for case in imported:
        report = json.loads(Path(case['features']['source_report']).read_text())
        assert case['question'] == report['question']
        assert case['dataset_id'] == Path(case['csv']).stem
    assignments = json.loads(Path('evals/designer/agent/scale/splits.json').read_text())
    membership = {name: split for split, names in assignments.items() for name in names}
    sources = {}
    for case in cases:
        sources.setdefault(case['dataset_id'], set()).add(membership[case['name']])
    assert all(len(memberships) == 1 for memberships in sources.values())


def test_capture_retries_twice_and_resumes_without_model_calls(tmp_path, monkeypatch):
    row = manifest_row(tmp_path, 'real')
    entries = [{'name': 'real', 'csv': str(tmp_path / row['csv_path']), 'question': 'Compare'}]
    reports = tmp_path / 'reports'
    from vis_agent.analyst.models import AnalysisReport
    good = AnalysisReport.model_validate(report_fixture())
    incomplete = good.model_copy(update={'analysis': None, 'result': None})
    calls = []

    async def analyze(*args):
        calls.append(args)
        return incomplete if len(calls) < 3 else good

    monkeypatch.setattr(capture, 'create_profiler', lambda model: object())
    monkeypatch.setattr(capture, 'create_analyst', lambda model: object())
    monkeypatch.setattr(capture, 'analyze_dataset', analyze)
    assert asyncio.run(capture._capture(entries, reports, 2)) == {}
    assert len(calls) == 3
    assert json.loads((reports / 'real.json').read_text())['result'] is not None
    monkeypatch.setattr(capture, 'create_profiler', lambda model: pytest.fail('cached report must not call models'))
    assert asyncio.run(capture._capture(entries, reports, 2)) == {}
    assert len(calls) == 3


def test_capture_reuses_frozen_phase4_report(tmp_path, monkeypatch):
    entries = [{'name': 'reused', 'features': {'source': 'phase4',
                'source_report': 'evals/designer/agent/reports/deaths_by_gender.json'}}]
    monkeypatch.setattr(capture, 'create_profiler', lambda model: pytest.fail('Phase 4 must not call models'))
    assert asyncio.run(capture._capture(entries, tmp_path / 'reports', 1)) == {}
    assert json.loads((tmp_path / 'reports/reused.json').read_text()) == report_fixture()


def test_capture_preserves_no_table_baseline_and_records_exceptions(tmp_path, monkeypatch):
    from vis_agent.analyst.models import AnalysisReport
    row = manifest_row(tmp_path, 'real')
    entries = [{'name': name, 'csv': str(tmp_path / row['csv_path']), 'question': name}
               for name in ['incomplete', 'exception']]
    report = AnalysisReport.model_validate(report_fixture()).model_copy(update={'analysis': None, 'result': None})
    calls = []

    async def analyze(store, profiler, analyst, dataset_id, question):
        calls.append(question)
        if question == 'exception':
            raise RuntimeError('offline simulated failure')
        return report

    monkeypatch.setattr(capture, 'create_profiler', lambda model: object())
    monkeypatch.setattr(capture, 'create_analyst', lambda model: object())
    monkeypatch.setattr(capture, 'analyze_dataset', analyze)
    failures = asyncio.run(capture._capture(entries, tmp_path / 'reports', 2))
    assert failures == {'exception': 'RuntimeError: offline simulated failure'}
    assert calls.count('incomplete') == calls.count('exception') == 3
    assert json.loads((tmp_path / 'reports/incomplete.json').read_text())['result'] is None
    assert not (tmp_path / 'reports/exception.json').exists()


def test_capture_main_only_keeps_pending_provenance(tmp_path, monkeypatch):
    entries = [{'name': name, 'intent': 'compare', 'metadata': {'chosen_chart': 'pie'},
                'features': {'source': 'phase4', 'source_report': 'evals/designer/agent/reports/deaths_by_gender.json'}}
               for name in ['ready', 'later']]
    write_json(tmp_path / 'selected.json', entries)
    write_json(tmp_path / 'seeded/seeded.json', [])
    write_json(tmp_path / 'splits.json', {'train': ['ready'], 'dev': ['later'], 'heldout': []})
    monkeypatch.setattr(capture, 'SCALE', tmp_path)
    monkeypatch.setattr(capture, 'load_dotenv', lambda: None)
    monkeypatch.setattr('sys.argv', ['capture', '--only', 'ready', '--concurrency', '1'])
    monkeypatch.setattr(capture, 'create_profiler', lambda model: pytest.fail('no model'))
    capture.main()
    assert [case['name'] for case in json.loads((tmp_path / 'cases.json').read_text())] == ['ready']
    decisions = json.loads((tmp_path / 'decisions.json').read_text())
    assert decisions['pending'] == ['later']
    assert decisions['cases'][0]['metadata']['chosen_chart'] == 'pie'
    assert decisions['provenance']
