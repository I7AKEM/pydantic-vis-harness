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


def test_help_offline():
    result = subprocess.run([sys.executable, '-m', 'evals.lead.run', '--help'], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert all(flag in result.stdout for flag in ('--corpus', '--out', '--only'))


def test_turn_history_and_capture(monkeypatch):
    from pydantic_ai import Agent
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.messages import TextPart
    module = runner()
    async def profile(*args):
        pass
    monkeypatch.setattr(module, 'profile_dataset', profile)
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
        'heldout_cases': 2, 'heldout_cases_ok': 1,
    }
    lines = capsys.readouterr().out.splitlines()
    assert all(text in lines[0] for text in ('revisions: 1', 'false questions: 1', 'requests: 12',
                                           'revision expected 2/3', 'redo analysis 1/1'))
    assert lines[1] == 'held-out cases 1/2'


def test_run_case_annotates_saved_requests_and_prints_fields(monkeypatch, capsys):
    import asyncio
    from pydantic_ai import Agent, RunContext
    from pydantic_ai.messages import TextPart
    from pydantic_ai.models.function import FunctionModel
    from vis_agent.analyst.models import AnalysisRevision
    from vis_agent.deps import AppDeps
    from vis_agent.requests.models import Caller

    module = runner()
    async def profile(*args):
        pass
    monkeypatch.setattr(module, 'profile_dataset', profile)

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
    assert turn['requests_used'] == 7 and turn['questioned'] is False
    printed = capsys.readouterr().out
    assert all(text in printed for text in ('revised=', turn['revised'], 'questioned=False', 'requests=7', 'revision=True'))


def test_run_case_profile_failure_keeps_reporting_fields(monkeypatch):
    import asyncio
    module = runner()
    async def profile(*args):
        raise RuntimeError('profile unavailable')
    monkeypatch.setattr(module, 'profile_dataset', profile)
    case = {**module.load_cases()[1], 'heldout': True}
    case['turns'] = [{**case['turns'][0], 'revision': False}]
    record = asyncio.run(module.run_case(case, None, None, None, None))
    turn = record['turns'][0]
    assert record['heldout'] is True
    assert not turn['tool_ok'] and not turn['outcome_ok']
    assert turn['revised'] is None and turn['requests_used'] is None and turn['questioned'] is False
    assert turn['revision_ok'] is True
