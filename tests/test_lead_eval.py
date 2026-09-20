"""Offline checks of the lead evaluation set and runner: cases, scoring, corpus sampling, help, and turn capture."""

import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart

ROOT = Path(__file__).resolve().parents[1]


def runner():
    return importlib.import_module('evals.lead.run')


def messages(name, content, args=None):
    return [ModelResponse(parts=[ToolCallPart(name, args or {}, tool_call_id='chosen')]),
            ModelRequest(parts=[ToolReturnPart(name, content, tool_call_id='chosen')])]


def test_cases():
    cases = json.loads((ROOT / 'evals/lead/cases.json').read_text())
    assert len(cases) == len({c['name'] for c in cases}) == 18
    for case in cases:
        csv = ROOT / case['csv']
        assert csv.is_file()
        assert case['turns'][0]['message'].endswith(
            '\n\nAttached CSV: [' + csv.name + '](/datasets/{dataset_id}/profile)')
        for turn in case['turns']:
            tools = turn['tool'] if isinstance(turn['tool'], list) else [turn['tool']]
            assert set(tools) <= {'draw', 'answer_question', 'revise', 'resume', 'none'}
            assert turn['outcome'] in {'chart', 'artifact', 'table', 'question', 'text', 'artifact_or_question', 'answered'}
            assert ('redo_analysis' in turn) == ('revise' in tools)
            if 'revision' in turn:
                assert isinstance(turn['revision'], bool)
    assert {c['name'] for c in cases if c.get('heldout')} == {'repair-jeddah-monthly', 'repair-two-units'}
    assert runner().load_cases() == cases


@pytest.mark.parametrize('tool,content,outcome', [
    ('draw', {'artifact': {'artifact_id': 'art_a'}, 'request_id': 'rq_a'}, 'artifact'),
    ('draw', {'artifact': {'artifact_id': 'art_a', 'chart': 'line'}}, 'chart'),
    ('draw', {'artifact': {'artifact_id': 'art_a', 'chart': None, 'rows': [['Al Olaya', 4]]}}, 'chart'),
    ('draw', {'clarification': {'question': 'Which?'}}, 'question'),
    ('draw', {'clarification': {'question': 'Which?'}}, 'artifact_or_question'),
    ('answer_question', {'rows': [[1]]}, 'table'),
    ('answer_question', {'rows': [[1]]}, 'answered'),
    ('draw', {'artifact': {'artifact_id': 'art_a'}}, 'answered'),
    ('find_artifact', [{'artifact_id': 'art_a'}], 'text'),
    ('resume', {'error': 'No unfinished request'}, 'text'),
])
def test_outcomes(tool, content, outcome):
    expected = 'none' if tool == 'find_artifact' else tool
    scored = runner().score_turn({'tool': expected, 'outcome': outcome}, messages(tool, content))
    assert scored['tool_ok'] and scored['outcome_ok']
    assert scored['redo_ok'] is None


def test_first_call_and_matching_return():
    captured = messages('profile_csv', {'artifact': {'artifact_id': 'wrong'}})
    captured += [ModelResponse(parts=[ToolCallPart('revise', '{"redo_analysis":false}', tool_call_id='chosen')]),
                 ModelRequest(parts=[ToolReturnPart('revise', {'artifact': {'artifact_id': 'wrong'}}, tool_call_id='other'),
                                     ToolReturnPart('revise', {'request_id': 'rq_a', 'artifact': {'artifact_id': 'art_a'}}, tool_call_id='chosen')])]
    scored = runner().score_turn({'tool': 'revise', 'outcome': 'artifact', 'redo_analysis': False}, captured)
    assert scored['tool_ok'] and scored['redo_ok'] and scored['outcome_ok']
    assert scored['request_id'] == 'rq_a' and scored['artifact_id'] == 'art_a'
    assert scored['tools_called'] == ['profile_csv', 'revise']


def test_prepared_csv_scores_the_leads_publication_and_preserved_values():
    expected = {'tool': 'draw', 'outcome': 'artifact', 'prepared_csv': True,
                'source_columns': ['region', 'sales'], 'source_rows': [['North', 10]],
                'charts': ['bar'], 'require_delivery': True, 'bindings': {'category': 'region', 'value': 'sales'},
                'axis_titles': {'bar': {'x': 'Sales', 'y': 'Region'}, 'column': {'x': 'Region', 'y': 'Sales'}}}
    artifact = {'artifact_id': 'art_a', 'chart': 'bar', 'columns': [{'name': 'region'}, {'name': 'sales'}],
                'rows': [['North', 10]], 'png_url': '/renders/a/chart.png',
                'spec': 'vis bar\naxisXTitle Sales\naxisYTitle Region\nbind\n  category region\n  value sales'}
    captured = messages('draw', {'request_id': 'rq_a', 'table': {'row_count': 1}})
    captured += messages('design_visualization', {'request_id': 'rq_a', 'design': {'chart': 'bar'}})
    captured += messages('render_visualization', {'request_id': 'rq_a', 'render': {'png_url': artifact['png_url']}})
    captured += messages('publish_visualization', {'request_id': 'rq_a', 'artifact': artifact})
    scored = runner().score_turn(expected, captured, '![Chart](/renders/a/chart.png)')
    assert all(scored[key] for key in ('tool_ok', 'outcome_ok', 'source_fidelity_ok', 'delegation_ok',
                                       'flow_ok', 'chart_ok', 'binding_ok', 'axis_titles_ok', 'delivery_ok'))
    artifact['spec'] = artifact['spec'].replace('vis bar', 'vis column')
    assert runner().score_turn(expected, captured)['axis_titles_ok'] is False
    artifact['spec'] = 'vis bar\nbind\n  category sales\n  value region'
    assert runner().score_turn(expected, captured)['binding_ok'] is False
    artifact['rows'] = [['North', 100]]
    assert runner().score_turn(expected, captured)['source_fidelity_ok'] is False
    captured += messages('consult_analyst', {'request_id': 'rq_a'})
    assert runner().score_turn(expected, captured)['delegation_ok'] is False


def test_prepared_csv_cases_have_exact_source_expectations_and_latency_targets():
    cases = runner().load_cases(ROOT / 'evals/lead/prepared/cases.json')
    assert len(cases) == 6
    for case in cases:
        assert (ROOT / case['csv']).is_file()
        assert case['brief']['producer_agent'] == 'data-agent'
        turn = case['turns'][0]
        assert turn['prepared_csv'] and turn['source_rows'] and turn['source_columns']
        assert turn['max_seconds'] == 60


def test_explicit_review_requires_a_review_call_before_publication():
    expected = {'tool': 'draw', 'outcome': 'artifact', 'review_required': True}
    artifact = {'artifact_id': 'art_a', 'review': {'status': 'reviewed'}}
    captured = messages('draw', {'request_id': 'rq_a'})
    captured += messages('publish_visualization', {'request_id': 'rq_a', 'artifact': artifact})
    assert runner().score_turn(expected, captured)['review_ok'] is False
    captured = messages('draw', {'request_id': 'rq_a'})
    captured += messages('review_visualization', {'request_id': 'rq_a', 'review': {'status': 'reviewed'}})
    captured += messages('publish_visualization', {'request_id': 'rq_a', 'artifact': artifact})
    assert runner().score_turn(expected, captured)['review_ok'] is True
    artifact['review']['status'] = 'not_reviewed'
    assert runner().score_turn(expected, captured)['review_ok'] is False


@pytest.mark.parametrize('tool,content,outcome,args', [
    ('draw', {'artifact': None}, 'artifact', {}),
    ('draw', {'artifact': None, 'clarification': {'question': 'Which?'}}, 'chart', {}),
    ('draw', {'rows': [[1]]}, 'table', {}),
    ('answer_question', {'rows': []}, 'table', {}),
    ('resume', {'artifact': {'artifact_id': 'art_a'}}, 'text', {}),
    ('revise', {'artifact': {}}, 'artifact', {}),
])
def test_failures(tool, content, outcome, args):
    expected = {'tool': tool, 'outcome': outcome}
    if tool == 'revise':
        expected['redo_analysis'] = False
    scored = runner().score_turn(expected, messages(tool, content, args))
    if tool == 'revise':
        assert scored['redo_ok'] is False
    else:
        assert scored['outcome_ok'] is False


def test_corpus_sample(tmp_path):
    rows = [{'dataset_id': f'csv-{i}', 'csv_path': f'{i}.csv',
             'occurrences': [{'question': f'Question {i}'}]} for i in range(20)]
    (tmp_path / 'manifest.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
    cases = runner().corpus_cases(tmp_path)
    import random
    assert [c['name'] for c in cases] == ['corpus-' + r['dataset_id'] for r in random.Random(11).sample(rows, 10)]
    assert all(c['turns'][0]['outcome'] == 'answered' and c['turns'][0]['tool'] == ['draw', 'answer_question'] for c in cases)

    twenty = runner().corpus_cases(tmp_path, count=20)
    assert [c['name'] for c in twenty] == ['corpus-' + r['dataset_id'] for r in random.Random(11).sample(rows, 20)]


def test_help_offline():
    result = subprocess.run([sys.executable, '-m', 'evals.lead.run', '--help'], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert all(flag in result.stdout for flag in ('--corpus', '--corpus-count', '--out', '--only', '--concurrency', '--dev20'))


def test_fixed_development_twenty_do_not_hide_unsupported_cases():
    gold = json.loads((ROOT / 'evals/lead/dev20-expectations.json').read_text())
    assert len(gold) == len({entry['id'] for entry in gold}) == 20
    by_id = {entry['id']: entry for entry in gold}
    assert by_id['vizcsv-839d109a0db9ce25']['handoff']['disposition'] == 'unsupported'
    assert by_id['vizcsv-97280400c00748a7']['original']['disposition'] == 'source_insufficient'
    assert by_id['vizcsv-e07c573241abdb02']['original']['no_image']
    assert by_id['vizcsv-85830f71807a6905']['handoff']['charts'] == ['table']


def test_renderable_twenty_is_a_separate_preregistered_cohort(tmp_path):
    from evals.lead.dev20 import cases
    gold = json.loads((ROOT / 'evals/lead/dev20-expectations.json').read_text())
    extra = json.loads((ROOT / 'evals/lead/dev20-additional.json').read_text())
    manifest = [{'dataset_id': entry['id'], 'csv_path': entry['id'] + '.csv',
                 'occurrences': [{'question': 'The original question.'}]} for entry in [*gold, extra]]
    (tmp_path / 'manifest.jsonl').write_text('\n'.join(json.dumps(row) for row in manifest))
    original = cases('original', tmp_path)
    handoff = cases('handoff', tmp_path)
    rendered = cases('renderable', tmp_path)
    assert len(original) == len(handoff) == len(rendered) == 20
    omitted = 'corpus-vizcsv-839d109a0db9ce25'
    assert omitted in {case['name'] for case in original} & {case['name'] for case in handoff}
    assert omitted not in {case['name'] for case in rendered}
    assert rendered[-1]['name'] == 'corpus-vizcsv-8b3fd04765e40d3a'
    assert all(case['evaluation_mode'] == 'renderable' for case in rendered)
    assert all(case['turns'][0]['require_render_evidence'] for case in rendered)
    assert all(case['brief']['producer_agent'] == 'data-agent' for case in rendered)
    assert all(case['caller_kind'] == 'agent' and case['caller_identity'] == 'eval-data-agent' for case in rendered)
    assert all(case['brief']['raw_question'] != case['original_question'] for case in rendered)


def test_audit_source_hash_covers_every_row_and_identifier():
    signature = runner().source_signature
    rows = [[str(index).zfill(5), index] for index in range(1000)]
    expected = signature(['code', 'value'], rows)
    assert expected['row_count'] == 1000
    assert signature(['code', 'value'], rows[:50]) != expected
    changed = [*rows[:-1], ['00999', 1000]]
    assert signature(['code', 'value'], changed) != expected
    assert signature(['code', 'value'], [[int(code), value] for code, value in rows]) != expected
    assert signature(['value', 'code'], rows) != expected


def test_strict_review_requires_pass_without_material_errors():
    expected = {'tool': 'draw', 'outcome': 'artifact', 'review_required': True, 'review_pass_required': True}
    artifact = {'artifact_id': 'art_a', 'review': {'status': 'reviewed', 'review': {'verdict': 'revise', 'findings': []}}}
    captured = messages('draw', {'request_id': 'rq_a'})
    captured += messages('render_visualization', {'request_id': 'rq_a'})
    captured += messages('review_visualization', {'request_id': 'rq_a'})
    captured += messages('publish_visualization', {'artifact': artifact})
    assert runner().score_turn(expected, captured)['review_ok'] is False
    artifact['review']['review']['verdict'] = 'pass'
    assert runner().score_turn(expected, captured)['review_ok'] is True
    artifact['review']['review']['findings'] = [{'level': 'error', 'owner': 'none'}]
    assert runner().score_turn(expected, captured)['review_ok'] is False


@pytest.mark.parametrize('field', ['level', 'severity'])
def test_strict_review_rejects_material_error_even_when_pass_is_returned(field):
    artifact = {'review': {'status': 'reviewed', 'review': {
        'verdict': 'pass', 'findings': [{field: 'error', 'owner': 'none'}],
    }}}
    assert runner().approved_review(artifact) is False
    artifact['review']['review']['findings'][0][field] = 'warning'
    assert runner().approved_review(artifact) is True


def test_strict_review_must_follow_the_latest_render_before_publication():
    expected = {'tool': 'draw', 'outcome': 'artifact', 'review_pass_required': True}
    artifact = {'artifact_id': 'art_a', 'review': {'status': 'reviewed', 'review': {'verdict': 'pass'}}}
    first = messages('draw', {'request_id': 'rq_a'})
    first += messages('render_visualization', {'request_id': 'rq_a'})
    first += messages('review_visualization', {'request_id': 'rq_a'})
    published = messages('publish_visualization', {'artifact': artifact})
    assert runner().score_turn(expected, first + published)['review_ok'] is True
    rerendered = first + messages('render_visualization', {'request_id': 'rq_a'})
    assert runner().score_turn(expected, rerendered + published)['review_ok'] is False
    reviewed = rerendered + messages('review_visualization', {'request_id': 'rq_a'})
    assert runner().score_turn(expected, reviewed + published)['review_ok'] is True
    assert runner().score_turn(expected, reviewed + published + messages('design_visualization', {}))['review_ok'] is False


def test_strict_visible_columns_are_not_credited_from_hidden_source_fields():
    expected = {'tool': 'draw', 'outcome': 'artifact', 'visible_columns': ['category', 'count', 'percentage']}
    artifact = {'spec': 'vis bar\nbind category category\nbind value count',
                'columns': [{'name': name} for name in ['category', 'count', 'percentage']]}
    result = runner().score_turn(expected, messages('draw', {'artifact': artifact}))
    assert result['visible_columns_ok'] is False
    artifact['spec'] = 'vis table'
    assert runner().score_turn(expected, messages('draw', {'artifact': artifact}))['visible_columns_ok'] is True


def test_strict_repetition_counts_cached_calls_too():
    expected = {'tool': 'draw', 'outcome': 'artifact', 'max_tool_calls': {'render_visualization': 1}}
    captured = messages('draw', {'request_id': 'rq_a'})
    captured += messages('render_visualization', {'cached': True}) * 2
    captured += messages('publish_visualization', {'artifact': {'artifact_id': 'art_a'}})
    assert runner().score_turn(expected, captured)['repetition_ok'] is False


def test_unsupported_chart_is_separate_from_an_approved_chart():
    expected = {'tool': ['draw', 'none'], 'outcome': 'handled', 'disposition': 'unsupported',
                'reply_patterns': ['cannot', 'map'], 'forbid_questions': True}
    result = runner().score_turn(expected, [], 'The current renderer cannot draw this route map.')
    assert result['outcome_ok'] and result['reply_ok']
    artifact = {'artifact_id': 'art_a', 'chart': 'scatter', 'png_url': '/renders/a/chart.png'}
    wrong = runner().score_turn(expected, messages('draw', {'artifact': artifact}),
                                'The current renderer cannot draw a map. Here is a scatter chart.')
    assert wrong['outcome_ok'] is False
    questioned = runner().score_turn(expected, messages('draw', {'clarification': {'question': 'Upload more data?'}}),
                                     'The current renderer cannot draw a map.')
    assert questioned['outcome_ok'] is False and questioned['reply_ok'] is False


def test_failure_preserves_lead_and_nested_specialist_usage(monkeypatch):
    import asyncio
    from pydantic_ai import Agent, RunContext
    from pydantic_ai.messages import TextPart
    from pydantic_ai.models.function import FunctionModel
    from vis_agent.deps import AppDeps

    module = runner()
    lead = Agent('test', deps_type=AppDeps)
    specialist = Agent('test')
    @lead.tool
    async def draw(ctx: RunContext[AppDeps]) -> dict:
        await specialist.run('Inspect', usage=ctx.usage)
        raise RuntimeError('Failure after specialist used a request')

    def respond(history, info):
        return ModelResponse(parts=[ToolCallPart('draw', {})])
    with lead.override(model=FunctionModel(respond)), specialist.override(
        model=FunctionModel(lambda history, info: ModelResponse(parts=[TextPart('Done')]))
    ):
        record = asyncio.run(module.run_case(module.load_cases()[1], lead, None, None, None))
    turn = record['turns'][0]
    assert not turn['outcome_ok']
    assert turn['usage']['requests'] == turn['requests_used'] == 2
    assert 'Failure after specialist' in turn['error']


@pytest.mark.parametrize('spec', [None, '', 123, []])
def test_fallback_without_executable_spec_has_no_visible_bindings(spec):
    artifact = {'artifact_id': 'art_fallback', 'chart': None, 'spec': spec,
                'no_chart_reason': 'Design failed', 'columns': [{'name': 'value'}], 'rows': [[5]]}
    assert runner().visible_columns(artifact) == set()
    turn = runner().score_turn({'tool': 'draw', 'outcome': 'artifact', 'visible_columns': ['value']},
                               messages('draw', {'artifact': artifact}))
    assert turn['visible_columns_ok'] is False


def test_scoring_exception_preserves_completed_model_reply_usage_and_messages(monkeypatch):
    import asyncio
    from pydantic_ai import Agent
    from pydantic_ai.messages import TextPart
    from pydantic_ai.models.function import FunctionModel
    module = runner()
    lead = Agent('test')
    def broken_score(*args):
        raise RuntimeError('Deliberate scorer failure')
    monkeypatch.setattr(module, 'score_turn', broken_score)
    case = {'name': 'scorer-failure', 'filename': 'tiny.csv', 'csv_text': 'value\n5\n',
            'turns': [{'message': 'Show it.', 'tool': 'none', 'outcome': 'text'}]}
    with lead.override(model=FunctionModel(lambda history, info: ModelResponse(parts=[TextPart('Completed answer')]))):
        record = asyncio.run(module.run_case(case, lead, None, None, None))
    turn = record['turns'][0]
    assert turn['reply'] == 'Completed answer'
    assert turn['messages'] and turn['usage']['requests'] == turn['requests_used'] == 1
    assert turn['outcome_ok'] is False and 'Deliberate scorer failure' in turn['evaluation_error']
    assert record['requests'] == record['artifacts'] == []
    assert module.summarize([record])['cases_ok'] == 0


def test_turn_deadline_keeps_evidence_and_continues_without_relaxing_pass_sla():
    import asyncio
    from pydantic_ai import Agent
    from pydantic_ai.messages import TextPart
    from pydantic_ai.models.function import FunctionModel
    module = runner()
    lead = Agent('test')
    calls = 0
    def respond(history, info):
        nonlocal calls
        calls += 1
        return ModelResponse(parts=[ToolCallPart('slow', {})] if calls == 1 else [TextPart('Next turn completed')])
    @lead.tool_plain
    async def slow() -> str:
        await asyncio.sleep(10)
        return 'Too late'
    expected = {'message': 'Show it.', 'tool': 'none', 'outcome': 'text', 'max_seconds': 60}
    case = {'name': 'deadline', 'filename': 'tiny.csv', 'csv_text': 'value\n5\n', 'turns': [expected, expected]}
    with lead.override(model=FunctionModel(respond)):
        record = asyncio.run(module.run_case(case, lead, None, None, None, turn_timeout=.05))
    first, second = record['turns']
    assert first['error'].startswith('TimeoutError: evaluation turn exceeded 0.05s')
    assert first['outcome_ok'] is False and first['latency_ok'] is True
    assert first['messages'] and first['usage']['requests'] == 1
    assert second['outcome_ok'] and second['reply'] == 'Next turn completed'
    assert record['turn_timeout_seconds'] == .05


def test_completed_case_checkpoints_survive_other_case_and_aggregate_errors(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    module = runner()
    lead = SimpleNamespace(model='test')
    deps = SimpleNamespace(profiler=None, analyst=None, designer=None, designer_fallback=None, reviewer=None)
    monkeypatch.setattr(module, 'teams_from_env', lambda *args: [SimpleNamespace(lead=lead, deps=deps, label='test')])
    async def fake_run(case, *args, **kwargs):
        if case['name'] == 'broken':
            raise RuntimeError('Unexpected case failure')
        record = {'name': case['name'], 'turns': [{**module.score_turn(case['turns'][0], [], 'Saved answer'),
                   'expected': case['turns'][0], 'reply': 'Saved answer', 'usage': {'requests': 1}}]}
        module.annotate_turns(record)
        return record
    monkeypatch.setattr(module, 'run_case', fake_run)
    cases = [{'name': name, 'turns': [{'tool': 'none', 'outcome': 'text'}]} for name in ('good', 'broken', 'next')]
    result = asyncio.run(module.evaluate(cases, tmp_path, concurrency=1, turn_timeout=120))
    assert result['summary']['cases'] == 3 and result['summary']['cases_ok'] == 2
    for case in cases:
        saved = json.loads((tmp_path / case['name'] / 'case.json').read_text())
        assert saved['run_configuration']['turn_timeout_seconds'] == 120
        assert saved['run_configuration']['application_code_sha256'] == result['application_code_sha256']
        assert not (tmp_path / case['name'] / 'case.json.tmp').exists()
    assert json.loads((tmp_path / 'broken/case.json').read_text())['turns'][0]['outcome_ok'] is False
    def broken_summary(*args):
        raise RuntimeError('Unexpected aggregate failure')
    monkeypatch.setattr(module, 'summarize', broken_summary)
    with pytest.raises(RuntimeError, match='aggregate failure'):
        asyncio.run(module.evaluate(cases, tmp_path / 'aggregate', concurrency=1))
    assert all((tmp_path / 'aggregate' / case['name'] / 'case.json').is_file() for case in cases)


def test_application_hash_is_separate_from_evaluator_hash(tmp_path, monkeypatch):
    module = runner()
    application = tmp_path / 'app.py'
    evaluator = tmp_path / 'eval.py'
    application.write_text('app version 1')
    evaluator.write_text('eval version 1')
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(module, 'code_paths', lambda: ([application], [evaluator]))
    original_app = module.code_fingerprint([application])
    original_eval = module.code_fingerprint([evaluator])
    combined = module.runtime_fingerprint()
    evaluator.write_text('eval version 2')
    assert module.code_fingerprint([application]) == original_app
    assert module.code_fingerprint([evaluator]) != original_eval
    assert module.runtime_fingerprint() != combined


@pytest.mark.parametrize('deadline', [0, -1, float('inf'), float('nan')])
def test_evaluation_deadline_must_be_finite_positive(deadline):
    import asyncio
    with pytest.raises(ValueError, match='positive finite'):
        asyncio.run(runner().evaluate([], turn_timeout=deadline))


def test_latency_percentiles_and_missing_usage_are_explicit():
    base = {'tool_ok': True, 'outcome_ok': True, 'redo_ok': None, 'revision_ok': None,
            'revised': None, 'questioned': False, 'expected': {'outcome': 'text'}}
    records = [{'name': str(i), 'turns': [{**base, 'seconds': i, 'requests_used': 1}]} for i in range(1, 21)]
    summary = runner().summarize(records)
    assert summary['requests'] == 20 and summary['usage_missing_turns'] == 0
    assert summary['latency_seconds']['p50'] == 10.5
    assert summary['latency_seconds']['p95'] == pytest.approx(19.05)


def test_numeric_fidelity_accepts_context_ranges_units_and_measured_category_counts():
    artifact = {'columns': [{'name': 'group', 'kind': 'category'},
                            {'name': 'violation_rate_per_100', 'kind': 'measure'}],
                'rows': [['A', 13.19], ['B', 7.17]], 'row_count': 2}
    check = runner().answer_numbers_match
    assert check('During 2023–2025, the 2 groups had 13.19 and 7.17 per 100.', artifact,
                 'Show rates in 2023-2025.')
    assert check('للأعمار 30–50، المعدلان 13.19 و7.17 لكل 100.', artifact,
                 'أعطني المعدلات للأعمار بين 30 و50.')
    assert check('The rate is 13.19 for ages 30-50.', artifact, 'Rates for ages between 30 and 50.')
    assert not check('During 2024–2026, the groups had 13.19 and 7.17.', artifact,
                     'Show rates in 2023-2025.')
    assert not check('The source rate is 99.', artifact, 'Show rates.')
    assert not check('The source rate is a decline of 13.19.', artifact, 'Show rates.')
    negative = {**artifact, 'rows': [['A', -13.19], ['B', 7.17]]}
    assert check('The source rate is -13.19.', negative, 'Show rates.')
    assert not check('The source rate is -13.19.', artifact, 'Show rates.')


def test_turn_history_and_capture(monkeypatch):
    from pydantic_ai import Agent
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.messages import TextPart
    module = runner()
    histories = []
    def respond(history, info):
        histories.append(history)
        if not isinstance(history[-1].parts[0], ToolReturnPart):
            return ModelResponse(parts=[ToolCallPart('draw', {'dataset_id': 'fake', 'question': 'q'})])
        return ModelResponse(parts=[TextPart('Here is the chart.')])
    lead = Agent('test')
    @lead.tool_plain
    def draw(dataset_id: str, question: str) -> dict:
        return {'request_id': 'rq_fake', 'artifact': {'artifact_id': 'art_fake'}}
    case = module.load_cases()[1]
    case = {**case, 'turns': case['turns'] * 2}
    with lead.override(model=FunctionModel(respond)):
        import asyncio
        result = asyncio.run(module.run_case(case, lead, None, None, None))
    assert len(result['turns']) == 2
    assert all(t['tool_ok'] and t['outcome_ok'] for t in result['turns'])
    assert all(t['tools_called'] == ['draw'] for t in result['turns'])
    assert len(histories[2]) > len(histories[0])
    assert result['turns'][1]['reply'] == 'Here is the chart.'


def test_a_turn_may_accept_either_continuation():
    expected = {'tool': ['resume', 'revise'], 'outcome': 'artifact', 'redo_analysis': True}
    resumed = runner().score_turn(expected, messages('resume', {'artifact': {'artifact_id': 'art_a'}}))
    assert resumed['tool_ok'] and resumed['outcome_ok'] and resumed['redo_ok'] is None
    revised = runner().score_turn(expected, messages('revise', {'artifact': {'artifact_id': 'art_b'}}, {'redo_analysis': True}))
    assert revised['tool_ok'] and revised['outcome_ok'] and revised['redo_ok'] is True
    drawn = runner().score_turn(expected, messages('draw', {'artifact': {'artifact_id': 'art_c'}}))
    assert not drawn['tool_ok']


def test_candidate_instructions_replace_the_leads_for_the_process(tmp_path, monkeypatch):
    import vis_agent.lead
    from evals.lead.run import use_instructions

    monkeypatch.setattr(vis_agent.lead, "LEAD_INSTRUCTIONS", "the source's instructions")
    path = tmp_path / "instructions.txt"
    path.write_text("Candidate instructions from the optimizer.", encoding="utf-8")
    assert use_instructions(path) == "Candidate instructions from the optimizer."
    assert vis_agent.lead.LEAD_INSTRUCTIONS == "Candidate instructions from the optimizer."


def test_a_retry_after_a_specialist_failure_is_scored_by_the_last_call():
    failed = {'status': 'failed', 'artifact': None, 'clarification': None, 'error': 'The analyst could not answer: TimeoutError'}
    delivered = {'artifact': {'artifact_id': 'art_b'}, 'request_id': 'rq_b'}
    turn = [ModelResponse(parts=[ToolCallPart('draw', {'question': 'q'}, tool_call_id='first')]),
            ModelRequest(parts=[ToolReturnPart('draw', failed, tool_call_id='first')]),
            ModelResponse(parts=[ToolCallPart('profile_csv', {}, tool_call_id='look')]),
            ModelRequest(parts=[ToolReturnPart('profile_csv', {'status': 'complete'}, tool_call_id='look')]),
            ModelResponse(parts=[ToolCallPart('draw', {'question': 'q'}, tool_call_id='second')]),
            ModelRequest(parts=[ToolReturnPart('draw', delivered, tool_call_id='second')])]
    scored = runner().score_turn({'tool': 'draw', 'outcome': 'artifact'}, turn)
    assert scored['tool'] == 'draw' and scored['tool_ok'] and scored['outcome_ok']
    assert scored['artifact_id'] == 'art_b' and scored['tools_called'] == ['draw', 'profile_csv', 'draw']
    assert scored['request_id'] == 'rq_b' and scored['questioned'] is False


@pytest.mark.parametrize('clarification', [None, {'question': 'Which hospital?', 'reason': 'No hospital column.'}])
def test_score_turn_reports_revision_and_question(clarification):
    content = {'request_id': 'rq_a', 'status': 'waiting' if clarification else 'done',
               'artifact': None if clarification else {'artifact_id': 'art_a'},
               'clarification': clarification, 'error': None}
    scored = runner().score_turn({'tool': 'draw', 'outcome': 'artifact_or_question'}, messages('draw', content))
    assert scored['request_id'] == 'rq_a'
    assert scored['questioned'] is (clarification is not None)


def test_question_and_request_id_follow_the_last_data_call():
    captured = messages('draw', {'request_id': 'rq_a', 'clarification': {'question': 'Which?'}})
    captured += messages('answer_question', {'rows': [[1]]})
    scored = runner().score_turn({'tool': 'draw', 'outcome': 'answered'}, captured)
    assert scored['tool_ok'] and scored['outcome_ok']
    assert scored['request_id'] is None and scored['questioned'] is False
    empty = runner().score_turn({'tool': 'none', 'outcome': 'text'}, [])
    assert empty['request_id'] is None and empty['questioned'] is False


def test_records_carry_revised_and_requests_used():
    problem = 'Need one row per month and measure'
    record = {
        'requests': [
            {'request_id': 'rq_plain', 'revision': None, 'requests_used': 0},
            {'request_id': 'rq_repaired', 'requests_used': 7,
             'revision': {'problem': problem, 'requested_change': 'Unpivot the two measures.',
                          'preserve': 'Keep the monthly totals.', 'evidence': []}},
        ],
        'turns': [
            {'request_id': 'rq_repaired', 'expected': {'revision': True}},
            {'request_id': 'rq_plain', 'expected': {'revision': False}},
            {'request_id': 'rq_repaired', 'expected': {'revision': False}},
            {'request_id': 'rq_plain', 'expected': {'revision': True}},
            {'request_id': 'rq_repaired', 'expected': {}},
            {'request_id': None, 'expected': {}},
            {'request_id': 'rq_missing', 'expected': {'revision': True}},
        ],
    }
    assert runner().annotate_turns(record) is None
    turns = record['turns']
    assert [t['revised'] for t in turns] == [problem, None, problem, None, problem, None, None]
    assert [t['requests_used'] for t in turns] == [7, 0, 7, 0, 7, None, None]
    assert [t['revision_ok'] for t in turns] == [True, True, False, False, None, None, False]
    missing = {'turns': [{'request_id': None, 'expected': {'revision': False}}]}
    runner().annotate_turns(missing)
    assert missing['turns'][0]['requests_used'] is None
    assert missing['turns'][0]['revised'] is None and missing['turns'][0]['revision_ok'] is True


def test_summary_counts_revisions_false_questions_and_heldout(capsys):
    plain = {'tool_ok': True, 'outcome_ok': True, 'redo_ok': None, 'revision_ok': None,
             'revised': None, 'questioned': False, 'requests_used': None, 'expected': {'outcome': 'text'}}
    records = [
        {'name': 'regular', 'turns': [
            {**plain, 'expected': {'outcome': 'chart'}, 'revised': 'Unpivot measures.',
             'revision_ok': True, 'redo_ok': True, 'requests_used': 7},
            {**plain, 'expected': {'outcome': 'question'}, 'questioned': True, 'requests_used': 2},
        ]},
        {'name': 'heldout-pass', 'heldout': True, 'turns': [
            {**plain, 'expected': {'outcome': 'chart'}, 'requests_used': 0, 'revision_ok': True},
        ]},
        {'name': 'heldout-question', 'heldout': True, 'turns': [
            {**plain, 'expected': {'outcome': 'chart'}, 'outcome_ok': False,
             'questioned': True, 'requests_used': 3, 'revision_ok': False},
        ]},
        {'name': 'no-request', 'heldout': False, 'turns': [plain]},
    ]
    summary = runner().summarize(records)
    assert summary == {
        'cases': 4, 'cases_ok': 3, 'turns': 5, 'tool_ok': 5, 'outcome_ok': 4,
        'redo_turns': 1, 'redo_ok': 1, 'revision_turns': 3, 'revision_ok': 2,
        'revisions': 1, 'false_questions': 1, 'requests': 12,
        'usage_missing_turns': 1,
        'heldout_cases': 2, 'heldout_cases_ok': 1,
        **{key: {'passed': 0, 'checked': 0} for key in (
            'fidelity_ok', 'delivery_ok', 'answer_fidelity_ok', 'analysis_reuse_ok', 'language_ok',
            'source_fidelity_ok', 'delegation_ok', 'chart_ok', 'binding_ok', 'axis_titles_ok', 'labels_ok',
            'flow_ok', 'review_ok', 'latency_ok', 'render_evidence_ok', 'visible_columns_ok',
            'repetition_ok', 'reply_ok', 'semantic_fidelity_ok')},
        'observed_outcomes': {},
        'latency_seconds': None,
    }
    lines = capsys.readouterr().out.splitlines()
    assert all(text in lines[0] for text in ('revisions: 1', 'false questions: 1', 'requests: 12',
                                           'revision expected 2/3', 'redo analysis 1/1'))
    assert lines[1] == 'held-out cases 1/2'


@pytest.mark.parametrize('failed_check', [
    'redo_ok', 'revision_ok', 'fidelity_ok', 'delivery_ok', 'answer_fidelity_ok',
    'analysis_reuse_ok', 'language_ok',
])
def test_summary_requires_both_repair_decisions_and_indicator_fidelity(failed_check):
    turn = {'tool_ok': True, 'outcome_ok': True, 'redo_ok': None, 'revision_ok': None,
            'revised': None, 'questioned': False, 'requests_used': 3,
            'expected': {'outcome': 'indicator'}, 'observed_outcome': 'indicator', failed_check: False}
    summary = runner().summarize([{'name': 'combined-regression', 'heldout': True, 'turns': [turn]}])
    assert summary['cases_ok'] == summary['heldout_cases_ok'] == 0
    assert summary['tool_ok'] == summary['outcome_ok'] == 1
    assert summary['requests'] == 3
    assert summary['observed_outcomes'] == {'indicator': 1}
    if failed_check not in {'redo_ok', 'revision_ok'}:
        assert summary[failed_check] == {'passed': 0, 'checked': 1}


def test_run_case_annotates_saved_requests_and_prints_fields(monkeypatch, capsys):
    import asyncio
    from pydantic_ai import Agent, RunContext
    from pydantic_ai.messages import TextPart
    from pydantic_ai.models.function import FunctionModel
    from vis_agent.analyst.models import AnalysisRevision
    from vis_agent.deps import AppDeps
    from vis_agent.requests.models import Caller

    module = runner()
    def respond(history, info):
        if not isinstance(history[-1].parts[0], ToolReturnPart):
            return ModelResponse(parts=[ToolCallPart('draw', {})])
        return ModelResponse(parts=[TextPart('Here is the chart.')])

    lead = Agent('test', deps_type=AppDeps)
    @lead.tool
    def draw(ctx: RunContext[AppDeps]) -> dict:
        dataset_id = ctx.deps.store.list_datasets()[0].dataset_id
        request = ctx.deps.requests.new_request('new', dataset_id, 'q', Caller(kind='chat'))
        request.revision = AnalysisRevision(problem='Need one row per month and measure',
                                            requested_change='Unpivot measures.', preserve='Keep totals.')
        request.requests_used = 7
        ctx.deps.requests.save_request(request)
        return {'request_id': request.request_id, 'artifact': {'artifact_id': 'art_fake'}, 'clarification': None}

    case = {**module.load_cases()[1], 'heldout': True}
    case['turns'] = [{**case['turns'][0], 'revision': True}]
    with lead.override(model=FunctionModel(respond)):
        record = asyncio.run(module.run_case(case, lead, None, None, None))
    turn = record['turns'][0]
    assert record['heldout'] is True
    assert turn['tool_ok'] and turn['outcome_ok'] and turn['revision_ok']
    assert turn['revised'] == 'Need one row per month and measure'
    assert turn['requests_used'] == 2 and turn['questioned'] is False
    assert record['requests'][0]['requests_used'] == 7
    printed = capsys.readouterr().out
    assert all(text in printed for text in ('revised=', turn['revised'], 'questioned=False', 'requests=2', 'revision=True'))


def test_run_case_csv_import_failure_keeps_reporting_fields(monkeypatch):
    import asyncio
    module = runner()
    def failed_import(*args):
        raise RuntimeError('CSV unavailable')
    monkeypatch.setattr(module.DatasetStore, 'import_csv', failed_import)
    case = {**module.load_cases()[1], 'heldout': True}
    case['turns'] = [{**case['turns'][0], 'revision': False}]
    record = asyncio.run(module.run_case(case, None, None, None, None))
    turn = record['turns'][0]
    assert record['heldout'] is True
    assert not turn['tool_ok'] and not turn['outcome_ok']
    assert turn['revised'] is None and turn['requests_used'] is None and turn['questioned'] is False
    assert turn['revision_ok'] is True


def test_indicator_cases_cover_routing_revisions_and_value_states():
    path = ROOT / 'evals/lead/indicator/cases.json'
    cases = runner().load_cases(path)
    assert len(cases) >= 12
    assert all((ROOT / c['csv']).is_file() for c in cases)
    turns = [t for c in cases for t in c['turns']]
    assert {'draw', 'answer_question', 'revise', 'resume'} <= {t['tool'] for t in turns}
    assert {True, False} == {t['analysis_reused'] for t in turns if 'analysis_reused' in t}
    assert any(None in t.get('metrics', {}).get('values', []) for t in turns)



def indicator_artifact(value=60):
    return {'artifact_id': 'art_a', 'chart': 'indicator', 'png_url': '/renders/a/chart.png',
            'row_count': 1, 'rows': [[value]], 'columns': [{'name': 'orders', 'unit': None}],
            'spec': 'vis indicator\ntitle Total\ndescription Total orders\ncards\n  - value orders'}



@pytest.mark.parametrize('mutation', ['wrong_value', 'missing_image', 'missing_reply_image', 'fallback', 'wrong_scale'])
def test_indicator_e2e_does_not_pass_on_artifact_existence_alone(mutation):
    artifact = indicator_artifact()
    reply = '![Total](/renders/a/chart.png)'
    expected = {'tool': 'draw', 'outcome': 'indicator', 'require_delivery': True,
                'metrics': {'values': [60], 'units': [None], 'card_count': 1}}
    if mutation == 'wrong_value':
        artifact['rows'] = [[61]]
    elif mutation == 'wrong_scale':
        artifact['rows'] = [[0.6]]
    elif mutation == 'missing_image':
        artifact['png_url'] = None
    elif mutation == 'missing_reply_image':
        reply = 'Here is the total.'
    else:
        artifact['no_chart_reason'] = 'The renderer failed.'
    result = runner().score_turn(expected, messages('draw', {'artifact': artifact}), reply)
    assert not all(result[k] for k in ('outcome_ok', 'fidelity_ok', 'delivery_ok'))



def test_indicator_e2e_records_distinct_unavailable_and_fallback_outcomes():
    expected = {'tool': 'draw', 'outcome': 'indicator'}
    value = {'artifact': indicator_artifact(None)}
    assert runner().score_turn(expected, messages('draw', value))['observed_outcome'] == 'unavailable_indicator'
    value['artifact']['no_chart_reason'] = 'Rendering failed.'
    result = runner().score_turn(expected, messages('draw', value))
    assert result['observed_outcome'] == 'fallback_table' and not result['outcome_ok']
    assert runner().observed_outcome({'status': 'failed'}, 'draw') == 'failure'
    assert runner().observed_outcome({'clarification': {'question': 'Which definition?'}}, 'draw') == 'clarification'



def test_final_answer_numeric_claims_are_checked_without_percent_rescaling():
    module = runner()
    artifact = indicator_artifact()
    assert module.answer_numbers_match('The total is 60. ![Chart](/renders/123/chart.png)', artifact, 'Total in 2025?')
    assert not module.answer_numbers_match('The total is 61. ![Chart](/renders/123/chart.png)', artifact, 'Total?')
    artifact['rows'] = [[0.6]]
    assert not module.answer_numbers_match('The rate is 60%.', artifact, 'What is the rate?')
    assert module.answer_numbers_match('The rate is 0.6%.', artifact, 'What is the rate?')


@pytest.mark.parametrize('link', [
    '/renders/da7b5f119a0b/chart.png',
    '/renders/48a96b712af7/chart.html?version=123#view456',
    '[/renders/2205da5bea28/chart.png](/renders/2205da5bea28/chart.png)',
    '[https://example.test/renders/556d4fa63741/chart.png](https://example.test/renders/556d4fa63741/chart.png)',
    '<https://example.test/renders/556d4fa63741/chart.png?trace=123>',
    '`/renders/da7b5f119a0b/chart.html`',
])
def test_answer_numbers_ignore_url_identifiers_but_keep_adjacent_claims(link):
    assert runner().answer_numbers_match(f'Total: 40. Chart: {link}', indicator_artifact(40), 'Total?')
    assert not runner().answer_numbers_match(f'Total: 41. Chart: {link}', indicator_artifact(40), 'Total?')


def test_answer_numbers_still_check_visible_numeric_link_labels():
    link = '/renders/da7b5f119a0b/chart.png'
    assert runner().answer_numbers_match(f'Total: [40]({link})', indicator_artifact(40), 'Total?')
    assert not runner().answer_numbers_match(f'Total: [41]({link})', indicator_artifact(40), 'Total?')


def test_answer_numbers_keep_real_precision_error_alongside_correct_value_and_chart_url():
    artifact = indicator_artifact(49.5578231292517)
    correct = 'M: 49.5578231292517%. /renders/9f9b7c03580b/chart.png'
    wrong = 'M: 49.5571768707483% (49.5578231292517%). /renders/9f9b7c03580b/chart.png'
    assert runner().answer_numbers_match(correct, artifact, 'Percentage by gender?')
    assert not runner().answer_numbers_match(wrong, artifact, 'Percentage by gender?')


def saved_answer_run():
    module = runner()
    public = indicator_artifact(1)
    public['row_count'] = 2  # The model-visible preview omits the second persisted row.
    expected = {'tool': 'draw', 'outcome': 'indicator', 'message': 'Show the supplied result.',
                'strict_source': True, 'require_render_evidence': True, 'max_seconds': 60}
    reply = 'The second value is 42. /renders/da7b5f119a0b/chart.png'
    captured = messages('draw', {'artifact': public})
    turn = module.score_turn(expected, captured, reply)
    turn.update(expected=expected, reply=reply, answer_fidelity_ok=False, seconds=66,
                latency_ok=False, review_ok=False, repetition_ok=False, usage={'requests': 13},
                messages=[{'preserved': 'raw message fixture'}])
    case = {'name': 'saved-handoff-case', 'evaluation_mode': 'renderable', 'turns': [turn],
            'assets': ['saved-handoff-case/renders/da7b5f119a0b/chart.png'],
            'artifacts': [{'artifact_id': 'art_a', 'report': {'result': {
                'columns': ['orders'], 'rows': [[1], [42]], 'row_count': 2}}}]}
    module.annotate_turns(case)
    return {'cases': [case], 'summary': module.summarize([case]),
            'evaluation_code_sha256': 'original-evaluator', 'provenance': {'frozen': 'original'}}


def test_offline_numeric_rescore_uses_full_saved_rows_without_changing_other_evidence():
    from copy import deepcopy
    from evals.lead.rescore_answers import rescore
    original = saved_answer_run()
    snapshot = deepcopy(original)
    rescored = rescore(original)
    assert original == snapshot
    assert rescored['cases'][0]['turns'][0]['answer_fidelity_ok'] is True
    assert rescored['summary']['cases_ok'] == 0  # Review, latency and repetition still fail.
    restored = deepcopy(rescored['cases'])
    restored[0]['turns'][0]['answer_fidelity_ok'] = False
    assert restored == original['cases']
    assert rescored['provenance'] == original['provenance']
    assert rescored['evaluation_code_sha256'] == original['evaluation_code_sha256']
    assert rescored['offline_rescore']['raw_summary'] == original['summary']


@pytest.mark.parametrize('damage', ['missing', 'truncated'])
def test_offline_numeric_rescore_refuses_missing_full_artifact_evidence(damage):
    from evals.lead.rescore_answers import rescore
    record = saved_answer_run()
    if damage == 'missing':
        record['cases'][0]['artifacts'] = []
    else:
        record['cases'][0]['artifacts'][0]['report']['result']['rows'] = [[1]]
    with pytest.raises(ValueError, match='persisted artifact rows'):
        rescore(record)



def test_count_unit_synonyms_do_not_weaken_currency_or_percentage_checks():
    artifact = indicator_artifact()
    expected = {'values': [60], 'units': [None], 'card_count': 1}
    for unit in ('count', 'counts', 'number', 'n', 'عدد', 'رقم'):
        artifact['columns'][0]['unit'] = unit
        assert runner().metric_values_match(expected, artifact)
    for unit in ('SAR', '%'):
        artifact['columns'][0]['unit'] = unit
        assert not runner().metric_values_match(expected, artifact)



@pytest.mark.parametrize('actual_unit,expected_unit', [
    ('percentage', '%'), ('%', 'percentage'), ('percent', '%'), (' Percentage ', '%'),
])
def test_explicit_percentage_aliases_match_without_rescaling(actual_unit, expected_unit):
    artifact = indicator_artifact(108.86)
    artifact['columns'][0]['unit'] = actual_unit
    expected = {'values': [108.86], 'units': [expected_unit], 'card_count': 1}
    assert runner().metric_values_match(expected, artifact)
    for changed_value in (1.0886, 10886):
        artifact['rows'] = [[changed_value]]
        assert not runner().metric_values_match(expected, artifact)



@pytest.mark.parametrize('unit', [None, 'fraction', 'ratio', 'percentage points', 'percentage_point', 'pct_unknown', 'SAR'])
def test_unknown_and_different_units_do_not_match_percentage(unit):
    artifact = indicator_artifact(108.86)
    artifact['columns'][0]['unit'] = unit
    expected = {'values': [108.86], 'units': ['%'], 'card_count': 1}
    assert not runner().metric_values_match(expected, artifact)



def test_lead_evidence_copies_render_assets_before_temporary_store_disappears(tmp_path, monkeypatch):
    import asyncio
    from pydantic_ai import Agent, RunContext
    from pydantic_ai.messages import TextPart
    from pydantic_ai.models.function import FunctionModel
    from vis_agent.deps import AppDeps
    module = runner()
    def respond(history, info):
        if isinstance(history[-1].parts[0], ToolReturnPart):
            return ModelResponse(parts=[TextPart('![Chart](/renders/fixture/chart.png)')])
        return ModelResponse(parts=[ToolCallPart('draw', {'dataset_id': 'fake', 'question': 'q'})])
    lead = Agent('test', deps_type=AppDeps)
    @lead.tool
    def draw(ctx: RunContext[AppDeps], dataset_id: str, question: str) -> dict:
        directory = ctx.deps.store.directory / 'renders/fixture'
        directory.mkdir(parents=True)
        (directory / 'chart.png').write_bytes(b'PNG fixture')
        (directory / 'chart.html').write_text('<p>fixture</p>')
        (directory / 'config.json').write_text('{}')
        return {'request_id': 'rq_fake', 'artifact': {'artifact_id': 'art_fake'}}
    with lead.override(model=FunctionModel(respond)):
        record = asyncio.run(module.run_case(module.load_cases()[1], lead, None, None, None, evidence_dir=tmp_path))
    assert len(record['assets']) == 3
    assert all((tmp_path / name).is_file() for name in record['assets'])
    assert record['turns'][0]['messages']
    assert record['turns'][0]['usage']['requests'] >= 1



def test_usage_serializes_decimal_cost_without_aborting_evidence():
    from decimal import Decimal
    from pydantic_ai.usage import RunUsage
    from pydantic_core import to_jsonable_python
    usage = RunUsage(requests=1)
    usage.details['cost'] = Decimal('0.000125')
    saved = json.loads(json.dumps(to_jsonable_python(usage)))
    assert saved['details']['cost'] == '0.000125'



def test_answer_numbers_accept_recorded_row_counts_and_verified_warning_totals():
    artifact = indicator_artifact(40)
    artifact['version'] = 2
    artifact['warnings'] = ['Total orders: the result covers 40 of the source total 60.']
    reply = 'Total orders: 40. Total rows: 1. Version: 2. Result covers 40 of the source total 60.'
    assert runner().answer_numbers_match(reply, artifact, 'Total orders?')
    assert not runner().answer_numbers_match(reply.replace('Total orders: 40.', 'Total orders: 41.'), artifact, 'Total orders?')



def test_attempting_withdrawn_resume_is_a_control_failure_even_after_text_recovery():
    from pydantic_ai.messages import RetryPromptPart, TextPart
    captured = [ModelResponse(parts=[ToolCallPart('resume', {}, tool_call_id='missing')]),
                ModelRequest(parts=[RetryPromptPart(content='Unknown tool name: resume', tool_name='resume', tool_call_id='missing')]),
                ModelResponse(parts=[TextPart('There is no unfinished request.')])]
    scored = runner().score_turn({'tool': 'none', 'outcome': 'text'}, captured, 'There is no unfinished request.')
    assert scored['outcome_ok'] and scored['observed_outcome'] == 'text'
    assert scored['tool'] == 'resume' and not scored['tool_ok']
    assert scored['tool_return'] is None



def test_final_answer_handles_bounded_change_magnitudes_without_absolute_matching():
    artifact = indicator_artifact(-80)
    assert runner().answer_numbers_match('Orders decreased by 80%.', artifact, 'What changed?')
    assert runner().answer_numbers_match('انخفضت الطلبات بنسبة 80%.', artifact, 'ما التغير؟')
    assert not runner().answer_numbers_match('Orders increased by 80%.', artifact, 'What changed?')
    assert not runner().answer_numbers_match('Orders decreased by -80%.', artifact, 'What changed?')
    assert not runner().answer_numbers_match('Orders decreased by +80%.', artifact, 'What changed?')
    assert not runner().answer_numbers_match('The result is 80%.', artifact, 'What changed?')
    assert not runner().answer_numbers_match('Orders did not decrease by 80%.', artifact, 'What changed?')
    artifact['rows'] = [[80]]
    assert not runner().answer_numbers_match('Orders decreased by 80%.', artifact, 'What changed?')
    assert runner().answer_numbers_match('Orders fell to 80.', artifact, 'What changed?')



def test_explicit_meaningful_count_unit_is_preserved_and_language_revision_is_scored():
    module = runner()
    artifact = indicator_artifact(18)
    gold = {'values': [18], 'units': ['person'], 'card_count': 1}
    assert not module.metric_values_match(gold, artifact)
    artifact['columns'][0]['unit'] = 'people'
    assert module.metric_values_match(gold, artifact)
    artifact['columns'][0]['unit'] = 'users'
    assert not module.metric_values_match(gold, artifact)
    assert module.metric_values_match({'values': [18], 'units': [None], 'card_count': 1}, artifact)
    artifact['spec'] = artifact['spec'].replace('title Total', 'title إجمالي المواطنين')+'\nlanguage ar'
    expected = {'tool': 'revise', 'outcome': 'indicator', 'redo_analysis': False, 'language': 'ar'}
    result = module.score_turn(expected, messages('revise', {'artifact': artifact}, {'redo_analysis': False}))
    assert result['language_ok']
    artifact['spec'] = artifact['spec'].replace('language ar', 'language en')
    assert not module.score_turn(expected, messages('revise', {'artifact': artifact}))['language_ok']
    regression = module.load_cases(ROOT / 'evals/lead/indicator/regressions.json')[0]
    assert regression['turns'][1]['message'].startswith('Make this card Arabic.')
    assert regression['turns'][1]['analysis_reused']
