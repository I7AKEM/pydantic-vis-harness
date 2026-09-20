"""Runtime constraints protect executable charts and source cells, not chart taste."""

import asyncio

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RunUsage, UsageLimits

from vis_agent.analyst.source import load_csv_report
from vis_agent.designer.agent import create_designer, design_chart
from vis_agent.designer.check import check_render_spec, check_spec
from vis_agent.store import DatasetStore


def source(tmp_path, text='city,amount\nA,12\nB,17\n'):
    store = DatasetStore(tmp_path)
    dataset = store.save_upload('answer.csv', text.encode())
    return load_csv_report(store, dataset.dataset_id, 'Compare the supplied amounts')


SPEC = 'vis bar\ntitle Amount by city\ndescription The supplied amount for each city\nbind\n  category city\n  value amount\n'


def test_designer_can_deliver_in_one_model_request_without_recommendations(tmp_path):
    report = source(tmp_path)
    calls = []

    def model(messages, info):
        calls.append(info)
        assert [tool.name for tool in info.output_tools] == ['deliver_design']
        assert [tool.name for tool in info.function_tools] == ['check_spec', 'chart_capabilities']
        return ModelResponse(parts=[ToolCallPart('deliver_design', {'spec': SPEC, 'explanation': 'Bars compare the supplied amounts.'})])

    designer = create_designer('test')
    with designer.override(model=FunctionModel(model)):
        result = asyncio.run(design_chart(report, designer))
    assert result.design.chart == 'bar'
    assert result.requests == len(calls) == 1
    assert result.check_calls == 0
    assert result.clarification is None
    assert result.revision is None


def test_expert_choices_are_not_rejected_by_catalogue_cardinality_or_palette_rules(tmp_path):
    report = source(tmp_path, 'city,amount\n' + '\n'.join(f'City{i},{i+1}' for i in range(20)))
    spec = SPEC.replace('vis bar', 'vis pie') + 'labels on\npalette\n  - #ffffff\n'
    assert not check_spec(spec, report.analysis.columns, report.result).ok
    assert check_render_spec(spec, report.analysis.columns, report.result).ok


def test_numeric_year_can_be_used_as_time_without_reprofiling(tmp_path):
    report = source(tmp_path, 'year,amount\n2024,12\n2025,17\n')
    spec = SPEC.replace('vis bar', 'vis line').replace('category city', 'time year')
    assert check_render_spec(spec, report.analysis.columns, report.result).ok


def test_unknown_bindings_and_nonnumeric_measure_cells_remain_repairable_errors(tmp_path):
    report = source(tmp_path)
    for spec in (SPEC.replace('value amount', 'value invented'), SPEC.replace('value amount', 'value city')):
        checked = check_render_spec(spec, report.analysis.columns, report.result)
        assert not checked.ok
        assert checked.violations[0].rule == 'C2'


def test_runtime_leaves_explicit_encoding_transformations_to_the_experts(tmp_path):
    report = source(tmp_path)
    for spec in (SPEC + 'limit 1\n', SPEC.replace('vis bar', 'vis stacked_bar') + 'percent true\n'):
        checked = check_render_spec(spec, report.analysis.columns, report.result)
        assert not any(issue.rule == 'source' for issue in checked.violations)


def test_parent_request_budget_is_not_replaced_by_a_larger_specialist_budget(tmp_path):
    report = source(tmp_path)
    calls = []

    def model(messages, info):
        calls.append(1)
        return ModelResponse(parts=[ToolCallPart('check_spec', {'spec': SPEC})])

    designer = create_designer('test')
    with designer.override(model=FunctionModel(model)):
        result = asyncio.run(design_chart(report, designer, usage=RunUsage(requests=3),
                                          usage_limits=UsageLimits(request_limit=4)))
    assert len(calls) == 1
    assert result.design is None
    assert result.warnings


def test_empty_source_is_a_technical_outcome_never_a_missing_data_question(tmp_path):
    report = source(tmp_path, 'city,amount\n')
    result = asyncio.run(design_chart(report, create_designer('test')))
    assert result.design is None
    assert result.clarification is None
    assert result.warnings == ['The supplied CSV contains no rows to visualize.']
