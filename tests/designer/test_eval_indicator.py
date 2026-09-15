"""The focused evaluator must catch semantic errors even in structurally valid cards."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.designer.agent import run
from evals.designer.agent.indicator.scoring import (
    IndicatorExpectation, _visible_unit_valid, metric_fidelity, numeric_text_matches, presentation_fit, rendered_fidelity,
)
from vis_agent.analyst.models import AnalysisReport, AnalysisRevision, Clarification
from vis_agent.designer.models import DesignReport
from vis_agent.designer.syntax import parse

ROOT = run.CASES_PATH.parent / 'indicator'


def fixture(name='dev_share_primary'):
    case = next(c for c in run.load_cases(ROOT / 'cases.json') if c.name == name)
    report = AnalysisReport.model_validate_json(Path(case.inputs['report']).read_text())
    gold = IndicatorExpectation.model_validate(case.expected_output['indicator'])
    return case, report, gold


def spec(gold):
    lines = ['vis indicator', 'title Summary', 'description Requested metrics', 'cards']
    for card in gold.cards:
        lines.append(f'  - value {card.value}')
        lines.extend(f'    context {c}' for c in card.context)
        lines.extend(f'    support {c}' for c in card.support)
    return parse('\n'.join(lines))


def test_focused_golds_are_independent_complete_and_split_by_family():
    cases = run.load_cases(ROOT / 'cases.json')
    assert len(cases) == 24
    assert len(run.load_cases(ROOT / 'cases.json', 'dev')) == 12
    assert len(run.load_cases(ROOT / 'cases.json', 'heldout')) == 12
    families = {}
    for case in cases:
        assert case.expected_output['charts'] is not None
        assert case.expected_output['indicator']
        families.setdefault(case.metadata['family'], set()).add(case.metadata['split'])
    assert all(len(splits) == 1 for splits in families.values())
    discovered = run.load_cases(ROOT / 'discovery.json')
    assert len(discovered) == 35
    assert {c.expected_output['indicator']['mode'] for c in discovered} == {
        'required', 'allowed', 'forbidden', 'incomplete', 'unavailable',
    }
    assert all(c.metadata['discovery'] and c.metadata['split'] == 'discovery' for c in discovered)
    manifest = json.loads((ROOT / 'discovery-manifest.json').read_text())
    assert len(manifest['cases']) == 35 and manifest['not_heldout']
    assert json.loads((ROOT / 'baseline.json').read_text())['deterministic_before_change']['score'] == '37/37'


def test_focused_loader_rejects_missing_independent_golds(tmp_path):
    cases = json.loads((ROOT / 'cases.json').read_text())[:1]
    cases[0]['report'] = str(ROOT / cases[0]['report'])
    cases[0]['charts'] = None
    path = tmp_path / 'cases.json'
    path.write_text(json.dumps(cases))
    with pytest.raises(ValueError, match='independent'):
        run.load_cases(path)


@pytest.mark.parametrize('mutation', ['wrong_primary', 'missing_support', 'extra_card', 'missing_card', 'wrong_scale', 'wrong_unit'])
def test_metric_errors_fail_even_when_a_card_and_png_exist(mutation):
    _, report, gold = fixture()
    parsed = spec(gold)
    assert metric_fidelity(gold, parsed, report)
    if mutation == 'wrong_primary':
        parsed.cards[0].value, parsed.cards[0].support = 'accepted', ['share']
    elif mutation == 'missing_support':
        parsed.cards[0].support = []
    elif mutation == 'extra_card':
        parsed.cards.append(parsed.cards[0].model_copy(update={'value': 'accepted', 'support': []}))
    elif mutation == 'missing_card':
        parsed.cards = []
    elif mutation == 'wrong_scale':
        report.result.rows[0][1] = 0.24
    else:
        report.analysis.columns[1].unit = None
    assert not metric_fidelity(gold, parsed, report)


def test_missing_scope_and_null_as_zero_fail():
    _, report, gold = fixture('dev_entity')
    parsed = spec(gold)
    parsed.cards[0].context = []
    assert not metric_fidelity(gold, parsed, report)
    _, report, gold = fixture('dev_unavailable')
    parsed = spec(gold)
    assert metric_fidelity(gold, parsed, report)
    report.result.rows[0][0] = 0
    assert not metric_fidelity(gold, parsed, report)


def test_disallowed_card_and_incomplete_answer_do_not_pass():
    _, _, gold = fixture('dev_admission_by_city')
    assert not presentation_fit(gold, 'indicator')
    assert presentation_fit(gold, 'column')
    _, _, gold = fixture('heldout_missing_years')
    assert not presentation_fit(gold, 'indicator')
    assert not presentation_fit(gold, 'table')
    assert presentation_fit(gold, None, clarified=True)


def missing_detail_revision():
    return AnalysisRevision(problem='Only the overall total is available; yearly results are missing.',
                            requested_change='Return one result for each requested year.',
                            preserve='Preserve the requested measure, years and units.')


@pytest.mark.parametrize('outcome', ['revision', 'clarification'])
def test_incomplete_result_accepts_explicit_repair_or_caller_clarification(tmp_path, outcome):
    case, report, gold = fixture('heldout_missing_years')
    output = DesignReport(dataset_id=report.dataset_id, question=report.question, language=report.language,
                          seconds=0, created_at=report.created_at,
                          revision=missing_detail_revision() if outcome == 'revision' else None,
                          clarification=Clarification(question='Which years are available?',
                                                      reason='The result contains only an overall total.')
                          if outcome == 'clarification' else None)
    ctx = SimpleNamespace(expected_output=case.expected_output, output=output, inputs=case.inputs)
    for evaluator in (run.Delivered, run.ChartAccepted, run.LanguageRight, run.BindingRight,
                      run.PresentationFit, run.MetricFidelity, run.Rendered):
        assert evaluator().evaluate(ctx) == 1, evaluator.__name__
    # This is a correct deferral, not evidence that any metric was delivered or drawn.
    assert not gold.cards and output.design is None
    assert not metric_fidelity(gold, None, report)
    evaluated = SimpleNamespace(name=case.name, output=output, inputs=case.inputs,
                                expected_output=case.expected_output, metadata=case.metadata,
                                scores={}, assertions={})
    entry = run._review_entries(SimpleNamespace(cases=[evaluated]), 'test', tmp_path)[0]
    assert entry['image'] is None and entry['chart'] is None and entry['spec'] == ''
    assert entry['observed_outcome'] == ('analysis_revision' if outcome == 'revision' else 'clarification')
    if outcome == 'revision':
        assert entry['analysis_revision'] == output.revision.model_dump(mode='json')
        assert output.revision.requested_change in entry['explanation']


def test_incomplete_repair_does_not_accept_empty_requests_or_a_partial_chart():
    _, _, gold = fixture('heldout_missing_years')
    revision = missing_detail_revision()
    assert presentation_fit(gold, None, revision=revision)
    assert not presentation_fit(gold, 'indicator', revision=revision)
    assert not presentation_fit(gold, 'table', clarified=True)
    assert not presentation_fit(gold, None, revision=AnalysisRevision(
        problem='', requested_change='', preserve=''))
    assert not presentation_fit(gold, None, revision={'requested_change': 'Missing detail'})


@pytest.mark.parametrize('name', ['dev_admission_total', 'dev_entity', 'dev_admission_by_city', 'dev_unavailable'])
def test_revision_cannot_replace_a_complete_result_or_unavailable_metric(name):
    case, report, gold = fixture(name)
    output = DesignReport(dataset_id=report.dataset_id, question=report.question, language=report.language,
                          seconds=0, created_at=report.created_at,
                          revision=missing_detail_revision())
    ctx = SimpleNamespace(expected_output=case.expected_output, output=output, inputs=case.inputs)
    assert not presentation_fit(gold, None, revision=output.revision)
    assert run.Delivered().evaluate(ctx) == 0
    assert run.PresentationFit().evaluate(ctx) == 0
    assert run.MetricFidelity().evaluate(ctx) == 0
    assert run.Rendered().evaluate(ctx) == 0


@pytest.mark.parametrize('expect', ['design', 'clarification'])
def test_ordinary_designer_delivery_golds_do_not_implicitly_allow_analysis_revision(expect):
    output = DesignReport(dataset_id='ds_test', question='Show the result.', language='English',
                          seconds=0, created_at='2026-09-15T00:00:00Z',
                          revision=missing_detail_revision())
    ctx = SimpleNamespace(expected_output={'expect': expect}, output=output)
    assert run.Delivered().evaluate(ctx) == 0


@pytest.mark.parametrize('text,value,passed', [
    ('24%', 24, True), ('0.24%', 24, False), ('2400%', 24, False),
    ('١٬٤٥٨', 1458, True), ('0', 0.000539399, False), ('0.0005394%', 0.000539399, True),
    ('Unavailable', None, True), ('0', None, False), ('غير متاح', None, True),
    ('9,007,199,254,740,993', 9007199254740993, True),
    ('9,007,199,254,740,992', 9007199254740993, False),
    ('1.46K', 1458, True), ('-148.75%', -148.75, True),
])
def test_numeric_text_is_scale_sensitive(text, value, passed):
    assert numeric_text_matches(text, value) is passed


def test_rendered_fidelity_uses_actual_draw_calls_and_bounds(tmp_path):
    _, report, gold = fixture('dev_admission_total')
    png, config = tmp_path / 'chart.png', tmp_path / 'config.json'
    png.write_bytes(b'png fixture')
    payload = {'gptvis': {'cards': [{'value': {'column': 'admissions', 'label': 'Admissions',
        'unit': None, 'state': 'available', 'display': '231', 'exact': None}, 'context': [], 'support': []}]}}
    config.write_text(json.dumps(payload))
    bounds = [{'text': '231', 'x': 10, 'y': 10, 'width': 50, 'height': 30, 'role': 'value', 'column': 'admissions'}]
    rendered = SimpleNamespace(png=png, config=config, width=300, height=200, texts=['231'], text_bounds=bounds)
    assert rendered_fidelity(gold, rendered, report)
    rendered.texts = ['230']
    assert not rendered_fidelity(gold, rendered, report)
    rendered.texts = ['231']
    bounds[0]['width'] = 500
    assert not rendered_fidelity(gold, rendered, report)
    bounds[0]['width'] = 50
    payload['gptvis']['cards'][0]['value']['display'] = '23100'
    config.write_text(json.dumps(payload))
    rendered.texts = ['23100']
    bounds[0]['text'] = '23100'
    assert not rendered_fidelity(gold, rendered, report)


def test_paired_relationships_detect_a_primary_that_does_not_follow_the_question():
    entries = []
    for name in ('dev_count_primary', 'dev_share_primary', 'dev_share_permuted'):
        case, _, gold = fixture(name)
        primary = gold.cards[0].value
        entries.append({'pair': 'claims', 'spec': f'vis indicator\ncards\n  - value {primary}',
            'scores': {'PresentationFit': 1, 'MetricFidelity': 1},
            'expected_indicator': case.expected_output['indicator']})
    assert run.paired_summary(entries) == [{'family': 'claims', 'observations': 3, 'passed': True}]
    # Even forged per-case success scores cannot hide a count/share switch failing to occur.
    entries[1]['spec'] = entries[0]['spec']
    assert not run.paired_summary(entries)[0]['passed']


def test_confirmation_is_new_frozen_and_original_heldout_is_marked_used():
    import hashlib
    confirmation = run.load_cases(ROOT / 'confirmation.json')
    assert len(confirmation) == 12
    assert all(c.metadata['split'] == 'confirmation' and not c.metadata['discovery'] for c in confirmation)
    existing = {c.metadata['family'] for c in run.load_cases(ROOT / 'cases.json')}
    assert existing.isdisjoint({c.metadata['family'] for c in confirmation})
    manifest = json.loads((ROOT / 'confirmation-manifest.json').read_text())
    assert not manifest['used_for_tuning']
    assert manifest['cases_sha256'] == hashlib.sha256((ROOT / 'confirmation.json').read_bytes()).hexdigest()
    for case in manifest['cases']:
        assert case['report_sha256'] == hashlib.sha256((ROOT / 'reports' / (case['name']+'.json')).read_bytes()).hexdigest()
    old = json.loads((ROOT / 'heldout-manifest.json').read_text())
    assert old['used_for_tuning'] and 'missing-year' in old['reason']
    by_name = {c.name: c.expected_output['indicator']['mode'] for c in confirmation}
    assert by_name['confirm_residential_age_bands'] == 'forbidden'
    assert by_name['confirm_missing_depots'] == by_name['confirm_missing_quarters'] == 'incomplete'


def test_actual_arabic_citizen_regression_preserves_raw_person_metadata():
    case = run.load_cases(ROOT / 'regressions.json')[0]
    report = AnalysisReport.model_validate_json(Path(case.inputs['report']).read_text())
    assert report.result.rows == [[18]]
    assert report.analysis.columns[0].unit == 'person'
    assert case.expected_output['indicator']['shared_heading'] == 'إجمالي عدد المواطنين'
    assert case.metadata['discovery'] and case.metadata['question_adapted_for_regression']


def test_actual_percentage_alias_regression_preserves_source_value_and_raw_unit():
    case = next(c for c in run.load_cases(ROOT / 'regressions.json')
                if c.name == 'regression_arabic_percentage_alias_108_86')
    report = AnalysisReport.model_validate_json(Path(case.inputs['report']).read_text())
    gold = IndicatorExpectation.model_validate(case.expected_output['indicator'])
    assert report.result.rows == [[108.86]]
    assert report.analysis.columns[0].unit == gold.cards[0].unit == 'percentage'
    assert report.analysis.columns[0].kind == 'measure'
    assert report.question == 'مثله بيانيا'
    assert report.analysis.columns[0].aggregate == 'sum'
    assert report.analysis.sql == 'SELECT "percentage_change" FROM "ds_338ef8d2926245ab93e513229c304951"'
    assert case.metadata['source_question_available'] and case.metadata['question_adapted_for_regression']
    assert gold.cards[0].unit_text == '%'
    assert gold.shared_heading == 'نسبة التغير'
    assert metric_fidelity(gold, spec(gold), report)
    report.analysis.columns[0].unit = '%'
    # A saved-report fixture must preserve raw source metadata even when display aliases agree.
    assert not metric_fidelity(gold, spec(gold), report)


@pytest.mark.parametrize('source', ['%', 'percent', 'percentage', ' Percentage '])
def test_visible_percent_aliases_require_the_symbol(source):
    assert _visible_unit_valid(source, '%')
    assert not _visible_unit_valid(source, 'percentage')
    assert not _visible_unit_valid(source, None)


@pytest.mark.parametrize('source', ['fraction', 'ratio', 'percentage points', 'percentage_point', 'pct_unknown', 'SAR'])
def test_unrelated_units_are_not_percent_aliases(source):
    assert not _visible_unit_valid(source, '%')
    assert _visible_unit_valid(source, source)


@pytest.mark.parametrize('number,unit,passes', [
    ('108.86', '%', True), ('108.86', 'percentage', False),
    ('10886', '%', False), ('1.0886', '%', False), ('108.86', '', False),
])
def test_percentage_alias_rendering_requires_symbol_without_rescaling(tmp_path, number, unit, passes):
    case = next(c for c in run.load_cases(ROOT / 'regressions.json')
                if c.name == 'regression_arabic_percentage_alias_108_86')
    report = AnalysisReport.model_validate_json(Path(case.inputs['report']).read_text())
    gold = IndicatorExpectation.model_validate(case.expected_output['indicator'])
    heading = gold.shared_heading
    column = gold.cards[0].value
    metric = {'column': column, 'label': heading, 'unit': 'percentage', 'state': 'available',
              'display': number + unit, 'number': number, 'unitLabel': unit, 'exact': None, 'exactNumber': None}
    payload = {'gptvis': {'title': heading, 'cards': [{'value': metric, 'context': [], 'support': []}]}}
    png, config = tmp_path / 'chart.png', tmp_path / 'config.json'
    png.write_bytes(b'png fixture')
    config.write_text(json.dumps(payload))
    bounds = [
        {'text': heading, 'x': 10, 'y': 10, 'width': 150, 'height': 30, 'role': 'label', 'column': column, 'card': 0},
        {'text': number, 'x': 10, 'y': 70, 'width': 90, 'height': 40, 'role': 'value', 'column': column, 'card': 0},
        {'text': unit, 'x': 105, 'y': 90, 'width': 100, 'height': 20, 'role': 'unit', 'column': column, 'card': 0},
    ]
    rendered = SimpleNamespace(png=png, config=config, width=300, height=200,
                               texts=[heading, number, unit], text_bounds=bounds)
    assert rendered_fidelity(gold, rendered, report) is passes


def test_visible_localized_unit_and_one_inner_heading_are_required(tmp_path):
    case = run.load_cases(ROOT / 'regressions.json')[0]
    report = AnalysisReport.model_validate_json(Path(case.inputs['report']).read_text())
    gold = IndicatorExpectation.model_validate(case.expected_output['indicator'])
    heading = gold.shared_heading
    column = gold.cards[0].value
    png, config = tmp_path / 'chart.png', tmp_path / 'config.json'
    png.write_bytes(b'png')
    payload = {'gptvis': {'title': heading, 'cards': [{'value': {'column': column, 'label': heading,
        'unit': 'person', 'state': 'available', 'display': '18 شخصًا', 'exact': None}, 'context': [], 'support': []}]}}
    config.write_text(json.dumps(payload))
    bounds = [{'text': heading, 'x': 10, 'y': 10, 'width': 150, 'height': 30, 'role': 'label', 'column': column, 'card': 0},
              {'text': '18 شخصًا', 'x': 10, 'y': 70, 'width': 50, 'height': 40, 'role': 'value', 'column': column}]
    rendered = SimpleNamespace(png=png, config=config, width=300, height=200, texts=[heading, '18 شخصًا'], text_bounds=bounds)
    assert rendered_fidelity(gold, rendered, report)
    payload['gptvis']['cards'][0]['value']['display'] = '18'
    config.write_text(json.dumps(payload))
    rendered.texts[-1] = bounds[-1]['text'] = '18'
    assert not rendered_fidelity(gold, rendered, report)
    payload['gptvis']['cards'][0]['value']['display'] = '18 شخصًا'
    config.write_text(json.dumps(payload))
    rendered.texts[-1] = bounds[-1]['text'] = '18 شخصًا'
    bounds[0]['role'] = 'title'
    assert not rendered_fidelity(gold, rendered, report)
    bounds[0]['role'] = 'label'
    rendered.texts.append(heading)
    assert not rendered_fidelity(gold, rendered, report)


def test_separate_numeric_and_unit_runs_need_real_adjacent_draw_evidence():
    from evals.designer.agent.indicator.scoring import _drawn_metric
    metric = {'column': 'rate', 'state': 'available', 'display': '9.91%', 'number': '9.91',
              'unitLabel': '%', 'exact': None, 'exactNumber': None}
    texts = ['9.91', '%']
    bounds = [{'column': 'rate', 'card': 0, 'role': 'value', 'text': '9.91', 'x': 10, 'y': 20, 'width': 70, 'height': 40},
              {'column': 'rate', 'card': 0, 'role': 'unit', 'text': '%', 'x': 85, 'y': 35, 'width': 12, 'height': 20}]
    assert _drawn_metric(metric, 'value', 0, texts, bounds) == '9.91'
    assert _drawn_metric(metric, 'value', 0, texts[:1], bounds[:1]) is None
    bounds[1]['x'] = 200
    assert _drawn_metric(metric, 'value', 0, texts, bounds) is None
    bounds[1]['x'] = 85
    bounds[1]['y'] = 100
    assert _drawn_metric(metric, 'value', 0, texts, bounds) is None
    bounds[1]['y'] = 35
    metric['number'] = '991'
    assert _drawn_metric(metric, 'value', 0, texts, bounds) is None
