import asyncio
import re
from datetime import datetime, timezone
from hashlib import sha256
from typing import get_args

import pytest
from pydantic_ai.messages import ModelResponse, RetryPromptPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from vis_agent.analyst.checks import summary_numbers_exist
from vis_agent.analyst.models import Analysis, AnalysisReport, AnalysisRevision, RevisionRound
from vis_agent.designer import models, syntax
from vis_agent.designer.agent import (
    DESIGNER_RULEBOOK, MAX_REQUESTS, build_prompt,
    create_designer, design_chart, grammar, instructions, render_design, render_id,
)
from vis_agent.designer.check import check_spec as run_check
from vis_agent.designer.recommend import recommend_charts as rank_charts
from vis_agent.models import DataBrief
from vis_agent.render import gptvis

from .conftest import cities, gender_share, monthly, table, two_units

DONUT = "vis donut\ntitle Gender share\ndescription Share by gender\nbind\n  category label\n  value share\nsort value desc\n"
ARABIC_DONUT = DONUT.replace("Gender share", "الحصة حسب الجنس").replace(
    "Share by gender", "توزيع الحصص حسب الجنس"
) + "language ar\n"
EXPLANATION = "The chart shows the share by gender. A donut compares the parts of the whole."


def report(columns, result, question="Share by gender?", language="English", summary="s", assumptions=()):
    return AnalysisReport(dataset_id="ds_1", question=question, language=language,
                          analysis=Analysis(sql="SELECT 1", columns=columns, summary=summary, assumptions=list(assumptions)),
                          result=result, seconds=0, created_at=datetime(2026, 9, 7, tzinfo=timezone.utc))


def tool_call(name, **args):
    return ModelResponse(parts=[ToolCallPart(tool_name=name, args=args)])


def last_return(messages):
    return [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)][-1]


def retries(messages):
    return [p for m in messages for p in m.parts if isinstance(p, RetryPromptPart)]


def run(source, model, **kwargs):
    designer = create_designer("test")
    with designer.override(model=model):
        return asyncio.run(design_chart(source, designer, **kwargs))


def test_render_id_is_stable_and_twelve_hex():
    source = report(*gender_share())
    digest = render_id(DONUT, source)
    assert re.fullmatch(r"[0-9a-f]{12}", digest)
    assert digest == sha256((DONUT + source.model_dump_json()).encode("utf-8")).hexdigest()[:12]
    assert render_id(DONUT, AnalysisReport.model_validate_json(source.model_dump_json())) == digest
    assert render_id(DONUT + "language ar\n", source) != digest
    changed = source.model_copy(update={"question": "Another question?"})
    assert render_id(DONUT, changed) != digest


@pytest.mark.skipif(gptvis.available() is not None, reason=gptvis.available() or "")
def test_render_design_merges_check_compromises(tmp_path):
    columns, result = monthly(3)
    for i, row in enumerate(result.rows):
        row[1] = 100 + i
    source = report(columns, result)
    spec = "vis line\ntitle Visits\ndescription Monthly visits\nbind\n  time month\n  value visits\nzero false\n"
    design = models.Design(spec=spec, chart="line", intent="trend", explanation="Monthly visits.",
                           considered=["line"], compromises=[])
    rendered = render_design(source, design, tmp_path)
    assert any(c.key == "zero" and c.message == "The value axis starts at 100 instead of zero."
               for c in rendered.compromises)
    assert all(path.is_file() for path in [rendered.png, rendered.html, rendered.config])


def test_render_design_refuses_a_failing_spec(tmp_path, monkeypatch):
    def unexpected_render(*args, **kwargs):
        pytest.fail("A failing spec must not reach the renderer")

    monkeypatch.setattr(gptvis, "render", unexpected_render)
    design = models.Design(spec="vis donut\n", chart="donut", intent="share", explanation=EXPLANATION,
                           considered=["donut"], compromises=[])
    with pytest.raises(ValueError, match="C2"):
        render_design(report(*gender_share()), design, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_render_design_rejects_unknown_renderer(tmp_path):
    design = models.Design(spec=DONUT, chart="donut", intent="share", explanation=EXPLANATION,
                           considered=["donut"], compromises=[])
    with pytest.raises(ValueError, match="Unknown renderer 'missing'"):
        render_design(report(*gender_share()), design, tmp_path, renderer="missing")


def test_prompt_is_bounded():
    columns, result = cities(60)
    result.rows[0][0] = "x" * 60
    brief = DataBrief(intent="compare", suggested_chart_type="bar", brand_colors=["#112233"],
                      caveats=["sampled"], column_descriptions={"city": "never shown"})
    prompt = build_prompt(report(columns, result, summary="City totals.", assumptions=["All cities."]), brief)
    assert len(prompt.preview) == 12 and prompt.preview_is_partial is True
    assert all(len(str(cell)) <= 40 for row in prompt.preview for cell in row)
    assert prompt.preview[0][0] == "x" * 39 + "…"
    assert prompt.preview[0][1] == 600
    assert prompt.row_count == 60
    assert prompt.intent == "compare" and prompt.suggested_chart_type == "bar"
    assert prompt.brand_colors == ["#112233"] and prompt.caveats == ["sampled"]
    assert prompt.summary == "City totals." and prompt.assumptions == ["All cities."]
    assert len(prompt.columns) == len(columns)
    assert prompt.columns[0].distinct == 60 and prompt.columns[0].longest_label == 60
    assert prompt.columns[1].minimum == 10 and prompt.columns[1].maximum == 600
    assert "SELECT" not in prompt.model_dump_json()
    assert "never shown" not in prompt.model_dump_json()
    assert result.rows[0][0] == "x" * 60
    assert build_prompt(report(*cities(5)), None).preview_is_partial is False


def test_grammar_and_instructions():
    text = grammar()
    assert "axisXTitle: text; the horizontal axis title" in text
    assert "axisYTitle: text; the vertical axis title" in text
    for key in [*syntax.KEYS, *syntax.STYLE_KEYS]:
        assert f"{key}:" in text
    for choice in [*get_args(models.SortOrder), *models.ROLES]:
        assert choice in text
    for _, kind in [*syntax.KEYS.values(), *syntax.STYLE_KEYS.values()]:
        if kind.startswith("enum:"):
            assert all(choice in text for choice in get_args(getattr(models, kind.removeprefix("enum:"))))
    assert instructions().startswith(DESIGNER_RULEBOOK.splitlines()[0])
    assert "\n\nGrammar:\n" + text in instructions()
    assert "donut:" in instructions() and "table:" in instructions()
    assert '"- value <column name>"' in text
    assert "ordinary bind must be empty" in text


def test_prompt_retains_partition_claim_and_materialized_result_limit():
    columns, result = gender_share()
    columns[-1].partition_by = []
    source = report(columns, result)
    assert build_prompt(source, None).columns[-1].partition_by == []
    result.row_count = 10
    assert build_prompt(source, None).preview_is_partial is True


def test_timeout_is_a_warning(monkeypatch):
    monkeypatch.setattr("vis_agent.designer.agent.DESIGN_TIMEOUT_SECONDS", 0.01)

    async def drive(messages, info):
        await asyncio.sleep(0.1)
        return tool_call("deliver_design", spec=DONUT, explanation=EXPLANATION)

    result = run(report(*gender_share()), FunctionModel(drive))
    assert result.design is None and len(result.warnings) == 1
    assert "The designer could not finish" in result.warnings[0] and "TimeoutError" in result.warnings[0]


@pytest.mark.parametrize("missing", ["analysis", "result"])
def test_incomplete_report_is_rejected(missing):
    source = report(*gender_share())
    setattr(source, missing, None)
    with pytest.raises(ValueError, match="The report needs an analysis and a result"):
        run(source, TestModel())


def test_previous_design_and_answers_reach_the_designer_prompt():
    from vis_agent.designer.agent import build_prompt, prompt_json
    from vis_agent.designer.models import PreviousDesign
    from vis_agent.models import QuestionAnswer

    source = report(*gender_share())
    plain = build_prompt(source, None)
    assert plain.previous is None and plain.clarifications == []
    assert '"previous"' not in prompt_json(plain) and '"clarifications"' not in prompt_json(plain)
    prompt = build_prompt(source, None, clarifications=[QuestionAnswer(question="Donut or pie?", answer="Donut")],
                          previous=PreviousDesign(spec="vis donut\ntitle Share\n", change="Make it blue"))
    assert prompt.previous.change == "Make it blue" and prompt.clarifications[0].answer == "Donut"
    legacy = build_prompt(source, None, previous=PreviousDesign(spec=None, change="Make it a blue indicator"))
    assert legacy.question == source.question
    assert '"previous":{"spec":null,"change":"Make it a blue indicator"}' in prompt_json(legacy)


def test_designer_revise_rules_reach_the_model_only_with_previous_work():
    from vis_agent.designer.agent import DesignerDeps, build_prompt, create_designer, prompt_json
    from vis_agent.designer.models import PreviousDesign

    source = report(*gender_share())
    designer = create_designer("test")
    seen = {}

    def drive(messages, info):
        seen["instructions"] = messages[0].instructions or ""
        return tool_call("deliver_design", spec=DONUT, explanation=EXPLANATION)

    for previous, expected in ((None, False), (PreviousDesign(spec="vis donut\n", change="Blue"), True),
                               (PreviousDesign(spec=None, change="Make it an indicator"), True)):
        prompt = build_prompt(source, None, previous=previous)
        deps = DesignerDeps(report=source, prompt=prompt, suggested=None)
        with designer.override(model=FunctionModel(drive)):
            asyncio.run(designer.run(prompt_json(prompt), deps=deps))
        assert ("A requested revision" in seen["instructions"]) is expected


def test_the_revision_round_reaches_the_prompt_and_loads_the_revise_rules():
    from vis_agent.designer.agent import DesignerDeps, prompt_json

    source = report(*gender_share())
    revision = RevisionRound(
        request=AnalysisRevision(problem="No series", requested_change="Add a series", preserve="The total"),
        reply="Added the series column.",
    )
    plain = build_prompt(source, None)
    assert '"revision"' not in prompt_json(plain)
    prompt = build_prompt(source, None, revision=revision)
    assert revision.reply in prompt_json(prompt)
    seen = {}

    def drive(messages, info):
        seen["instructions"] = messages[0].instructions or ""
        return tool_call("deliver_design", spec=DONUT, explanation=EXPLANATION)

    designer = create_designer("test")
    deps = DesignerDeps(report=source, prompt=prompt, suggested=None)
    with designer.override(model=FunctionModel(drive)):
        asyncio.run(designer.run(prompt_json(prompt), deps=deps))
    assert "A requested revision" in seen["instructions"]


@pytest.mark.parametrize('repair', [True, False])
def test_delivery_repairs_invalid_bindings_once_then_stops(repair):
    calls = []

    def drive(messages, info):
        calls.append(1)
        spec = DONUT if repair and len(calls) == 2 else DONUT.replace('value share', 'value invented')
        return tool_call('deliver_design', spec=spec, explanation=EXPLANATION)

    designed = run(report(*gender_share()), FunctionModel(drive))
    assert len(calls) == 2
    assert (designed.design is not None) is repair
    if not repair:
        assert designed.clarification is None
        assert 'invented' in designed.warnings[0]


def test_required_columns_are_enforced_inside_one_designer_run():
    from tests.designer.conftest import column

    columns = [column("city", "category"), column("wealth", "category"), column("count", "measure")]
    source = report(columns, table(columns, [["Riyadh", "Rich", 3], ["Riyadh", "Poor", 2]]))
    calls = []

    def drive(messages, info):
        calls.append(1)
        if len(calls) == 1:
            spec = "vis bar\ntitle Counts\ndescription Counts by city\nbind\n  category city\n  value count\n"
        else:
            spec = ("vis grouped_bar\ntitle Counts\ndescription Counts by city and wealth\nbind\n"
                    "  category city\n  value count\n  group wealth\n")
        return tool_call("deliver_design", spec=spec, explanation="Counts by city and wealth.")

    designed = run(source, FunctionModel(drive), required_columns=["wealth"])
    assert len(calls) == 2
    assert designed.design is not None and "group wealth" in designed.design.spec


def test_optional_check_tool_is_withdrawn_when_budget_is_spent():
    calls = []

    def drive(messages, info):
        calls.append(1)
        if len(calls) <= 3:
            names = [tool.name for tool in info.function_tools]
            assert 'check_spec' in names
            assert 'chart_capabilities' in names
            return tool_call('check_spec', spec=DONUT)
        names = [tool.name for tool in info.function_tools]
        assert 'check_spec' not in names
        assert 'chart_capabilities' in names
        return tool_call('deliver_design', spec=DONUT, explanation=EXPLANATION)

    designed = run(report(*gender_share()), FunctionModel(drive))
    assert designed.design is not None
    assert designed.check_calls == 3
    assert len(calls) == 4


def test_model_ignoring_withdrawn_check_tool_ends_within_request_budget():
    calls = []

    def drive(messages, info):
        calls.append(1)
        return tool_call('check_spec', spec=DONUT)

    designed = run(report(*gender_share()), FunctionModel(drive))
    assert len(calls) <= MAX_REQUESTS
    assert designed.design is None
    assert designed.clarification is None
    assert designed.warnings


def test_check_budget_failure_retains_execution_diagnostics():
    invalid = DONUT.replace('value share', 'value invented')
    calls = []

    def drive(messages, info):
        calls.append(1)
        if len(calls) <= 3:
            return tool_call('check_spec', spec=invalid)
        return tool_call('deliver_design', spec=invalid, explanation=EXPLANATION)

    designed = run(report(*gender_share()), FunctionModel(drive))
    assert designed.design is None
    assert designed.check_calls == 3
    assert 'invented' in designed.warnings[0]
    assert designed.clarification is None


def test_prompt_projects_source_meanings_and_requested_language_labels_to_result_aliases():
    from vis_agent.models import DisplayLabels
    from .conftest import column

    columns = [column("sex_code", "category", source="gender"),
               column("marital", "category", source="marital_status"),
               column("gender_total", "measure", source="gender", aggregate="count")]
    source = report(columns, table(columns, [["M", "M", 12]]), language="Arabic")
    brief = DataBrief(
        code_meanings={"gender": {"M": "Male"}, "marital_status": {"M": "Married"}},
        display_labels={
            "ar": DisplayLabels(column_labels={"gender": "الجنس", "marital_status": "الحالة الاجتماعية"},
                                value_labels={"gender": {"M": "ذكور"}, "marital_status": {"M": "متزوج"}}),
            "en": DisplayLabels(column_labels={"gender": "Gender"}, value_labels={"gender": {"M": "Male"}}),
        },
    )
    prompt = build_prompt(source, brief)
    assert prompt.code_meanings == {"sex_code": {"M": "Male"}, "marital": {"M": "Married"}}
    assert prompt.display_labels.column_labels == {"sex_code": "الجنس", "marital": "الحالة الاجتماعية"}
    assert prompt.display_labels.value_labels == {"sex_code": {"M": "ذكور"}, "marital": {"M": "متزوج"}}
    assert "gender_total" not in prompt.display_labels.column_labels
    assert source.result.rows == [["M", "M", 12]]


@pytest.mark.parametrize("use_check", [False, True])
def test_source_approved_labels_are_saved_verbatim_without_an_extra_model_call(use_check):
    from vis_agent.models import DisplayLabels
    from .conftest import column

    columns = [column("gender", "category", source="gender"), column("n", "measure")]
    source = report(columns, table(columns, [["M", 12], ["F", 17]]), language="Arabic")
    brief = DataBrief(code_meanings={"gender": {"M": "Male", "F": "Female"}},
                      display_labels={"ar": DisplayLabels(column_labels={"gender": "الجنس"},
                                                          value_labels={"gender": {"M": "ذكور"}})})
    proposed = ('vis bar\ntitle العدد حسب الجنس\ndescription الأعداد الواردة حسب الجنس\nlanguage ar\n'
                'bind\n  category gender\n  value n\ncolumnLabels\n  - ["gender", "عنوان مختلف"]\n'
                'valueLabels\n  - ["gender", "M", "ترجمة مختلفة"]\n  - ["gender", "F", "إناث"]\n')
    calls, checked = [], []

    def drive(messages, info):
        calls.append(1)
        if use_check and len(calls) == 1:
            return tool_call("check_spec", spec=proposed)
        if use_check:
            checked.append(last_return(messages).model_response_object()["canonical"])
        return tool_call("deliver_design", spec=proposed, explanation="مقارنة الأعداد حسب الجنس.")

    designed = run(source, FunctionModel(drive), brief=brief)
    assert designed.design is not None, designed.warnings
    saved = syntax.parse(designed.design.spec)
    assert saved.column_labels == {"gender": "الجنس"}
    assert saved.value_labels == {"gender": {"M": "ذكور", "F": "إناث"}}
    assert len(calls) == (2 if use_check else 1)
    assert not checked or checked == [designed.design.spec]
    assert source.result.rows == [["M", 12], ["F", 17]]


def test_display_mapping_merge_preserves_the_syntax_retry_path():
    from vis_agent.models import DisplayLabels

    calls = []
    brief = DataBrief(display_labels={"en": DisplayLabels(column_labels={"city": "City name"})})
    spec = "vis bar\ntitle Cities\ndescription Counts by city\nbind\n  category city\n  value violations\n"

    def drive(messages, info):
        calls.append(1)
        return tool_call("deliver_design", spec="vis invented\n" if len(calls) == 1 else spec,
                         explanation="Bars compare the city counts.")

    designed = run(report(*cities()), FunctionModel(drive), brief=brief)
    assert designed.design is not None
    assert len(calls) == 2
    assert syntax.parse(designed.design.spec).column_labels["city"] == "City name"
