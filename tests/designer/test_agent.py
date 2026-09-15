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
from vis_agent.analyst.models import Analysis, AnalysisReport
from vis_agent.designer import models, syntax
from vis_agent.designer.agent import (
    DESIGNER_RULEBOOK, EMPTY_RESULT, MAX_REQUESTS, build_prompt,
    create_designer, design_chart, grammar, instructions, render_design, render_id,
)
from vis_agent.designer.check import check_spec as run_check
from vis_agent.designer.recommend import recommend_charts as rank_charts
from vis_agent.models import DataBrief
from vis_agent.render import gptvis

from .conftest import cities, gender_share, monthly, table

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


def test_indicator_designer_uses_normal_recommend_check_and_delivery_path():
    from .conftest import single_number

    spec = "vis indicator\ntitle Total visitors\ndescription Reported visitor total\ncards\n  - value total\n"

    def drive(messages, info):
        returns = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
        if not returns:
            return tool_call("recommend_charts", intent="summary")
        returned = last_return(messages).model_response_object()
        if len(returns) == 1:
            first = returned["candidates"][0]
            assert first["name"] == "indicator" and first["cards"][0]["value"] == "total"
            return tool_call("check_spec", spec=spec)
        assert returned["ok"]
        return tool_call("deliver_design", spec=returned["canonical"],
                         explanation="The card shows the reported total. A headline number answers the total request.")

    result = run(report(*single_number(), question="What is the total visitor count?"), FunctionModel(drive))
    assert result.design.chart == "indicator" and result.design.intent == "summary"
    assert result.check_calls == 1 and result.requests == 3
    assert result.clarification is None and result.warnings == []


def test_indicator_nested_syntax_error_is_repairable_with_existing_check_budget():
    from .conftest import single_number

    spec = "vis indicator\ntitle Total\ndescription Reported total\ncards\n  - value total\n"

    def drive(messages, info):
        returns = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
        if not returns:
            return tool_call("check_spec", spec=spec + "    formula sum(total)\n")
        returned = last_return(messages).model_response_object()
        if len(returns) == 1:
            assert returned["violations"][0]["rule"] == "syntax"
            assert returned["violations"][0]["line"] == 6
            return tool_call("check_spec", spec=spec)
        assert returned["ok"]
        return tool_call("deliver_design", spec=returned["canonical"], explanation="The indicator shows the total.")

    result = run(report(*single_number()), FunctionModel(drive))
    assert result.design.chart == "indicator"
    assert result.check_calls == 2 and result.requests == 3


@pytest.mark.parametrize("use_check_tool", [True, False])
def test_selected_composition_intent_cannot_deliver_indicator_even_with_complete_bindings(use_check_tool):
    from .conftest import column

    columns = [column("total", "measure"), column("hardware", "measure"), column("software", "measure")]
    source = report(columns, table(columns, [[900, 300, 600]]), question="Show total sales and the product breakdown.")
    indicator = ("vis indicator\ntitle Sales\ndescription Sales totals\ncards\n"
                 "  - value total\n  - value hardware\n  - value software\n")
    table_spec = "vis table\ntitle Sales breakdown\ndescription Sales by product and total sales\n"
    calls = 0

    def drive(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return tool_call("recommend_charts", intent="composition")
        if calls == 2:
            if use_check_tool:
                return tool_call("check_spec", spec=indicator)
            return tool_call("deliver_design", spec=indicator, explanation="The cards show sales.")
        if calls == 3:
            if use_check_tool:
                checked = last_return(messages).model_response_object()
                assert not checked["ok"] and any(v["rule"] == "I7" for v in checked["violations"])
            else:
                assert "I7" in retries(messages)[-1].content
            return tool_call("deliver_design", spec=table_spec, explanation="The table preserves the product breakdown and total.")
        pytest.fail("Repair should complete within the existing request budget")

    result = run(source, FunctionModel(drive))
    assert result.design.chart == "table" and result.design.intent == "composition"
    assert result.requests == 3 and result.clarification is None


def test_render_design_rechecks_selected_intent_before_rendering(tmp_path):
    from .conftest import single_number

    source = report(*single_number())
    spec = "vis indicator\ntitle Total\ndescription Reported total\ncards\n  - value total\n"
    design = models.Design(spec=spec, chart="indicator", intent="composition", explanation="Components.",
                           considered=["indicator"], compromises=[])
    with pytest.raises(ValueError, match="I7"):
        render_design(source, design, tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("starting_requests", [None, 7])
def test_happy_path(starting_requests):
    source = report(*gender_share(), question="ما الحصة حسب الجنس؟", language="Arabic")
    considered = []

    def drive(messages, info):
        returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
        if not returns:
            return tool_call("recommend_charts", intent="share")
        returned = last_return(messages).model_response_object()
        if len(returns) == 1:
            assert len(returned["candidates"]) <= 5
            assert returned["candidates"][0]["name"] == "donut" and returned["intent"] == "share"
            considered.extend(c["name"] for c in returned["candidates"])
            return tool_call("check_spec", spec=ARABIC_DONUT)
        assert returned["ok"] and returned["canonical"] == syntax.to_text(syntax.parse(ARABIC_DONUT))
        return tool_call("deliver_design", spec=returned["canonical"],
                         explanation="يوضح الرسم الحصة حسب الجنس. يقارن الرسم الحلقي أجزاء الكل.")

    usage = RunUsage(requests=starting_requests) if starting_requests is not None else None
    result = run(source, FunctionModel(drive), usage=usage, brief=DataBrief(suggested_chart_type="donut"))
    assert result.design.spec == result.check.canonical
    assert result.design.chart == "donut" and result.design.intent == "share"
    assert result.design.considered == considered
    assert any("legend stays" in c.message for c in result.design.compromises)
    assert result.check.ok and result.requests == 3 and result.check_calls == 1
    assert result.model.startswith("function") and result.clarification is None
    assert result.warnings == []
    if usage is not None:
        assert usage.requests == starting_requests + 3


def test_repair_after_violation():
    def drive(messages, info):
        returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
        if not returns:
            return tool_call("check_spec", spec=DONUT + "emphasis\n  - Femlae\n")
        returned = last_return(messages).model_response_object()
        if len(returns) == 1:
            assert any(v["rule"] == "C9" for v in returned["violations"])
            return tool_call("check_spec", spec=DONUT + "emphasis\n  - Female\n")
        assert returned["ok"]
        return tool_call("deliver_design", spec=returned["canonical"], explanation=EXPLANATION)

    result = run(report(*gender_share()), FunctionModel(drive))
    assert result.design is not None and result.check.ok
    assert result.check_calls == 2 and result.warnings == []


def test_shortlist_preserves_phase_three_ranking():
    source = report(*gender_share())
    expected = rank_charts(source.analysis.columns, source.result, intent="share")

    def drive(messages, info):
        returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
        if not returns:
            return tool_call("recommend_charts", intent="share")
        returned = last_return(messages).model_response_object()
        assert returned["candidates"] == [candidate.model_dump() for candidate in expected.candidates[:5]]
        assert returned["rejected"] == [rejection.model_dump() for rejection in expected.rejected]
        return tool_call("deliver_design", spec=DONUT, explanation=EXPLANATION)

    result = run(source, FunctionModel(drive))
    assert result.design.considered == [c.name for c in expected.candidates[:5]]
    assert result.design.considered[0] == "pie"


@pytest.mark.parametrize("repair", [True, False])
def test_delivery_rechecks_once(repair):
    attempts = []

    def drive(messages, info):
        attempts.append(1)
        if len(attempts) == 1:
            return tool_call("deliver_design", spec=DONUT.replace("value share", "value missing"), explanation=EXPLANATION)
        assert "C2" in retries(messages)[-1].content
        return tool_call("deliver_design", spec=DONUT if repair else DONUT.replace("value share", "value missing"),
                         explanation=EXPLANATION)

    result = run(report(*gender_share()), FunctionModel(drive))
    assert len(attempts) == 2 and result.check_calls == 0
    if repair:
        assert result.design is not None and result.check.ok and result.warnings == []
        assert result.design.intent is None and result.design.considered == []
    else:
        assert result.design is None and result.check is None
        assert len(result.warnings) == 1 and "C2" in result.warnings[0]


@pytest.mark.parametrize("language,question,first_title,correct_title", [
    ("Arabic", "ما الحصة حسب الجنس؟", "Gender share", "الحصة حسب الجنس"),
    ("English", "Share by gender?", "الحصة حسب الجنس", "Gender share"),
])
def test_language_is_set_and_title_script_checked(language, question, first_title, correct_title):
    source = report(*gender_share(), question=question, language=language)

    def drive(messages, info):
        if not retries(messages):
            return tool_call("deliver_design", spec=DONUT.replace("Gender share", first_title), explanation=EXPLANATION)
        assert f"Write the title in {language}." in retries(messages)[-1].content
        return tool_call("deliver_design", spec=DONUT.replace("Gender share", correct_title), explanation=EXPLANATION)

    result = run(source, FunctionModel(drive))
    assert result.design is not None and result.warnings == []
    assert syntax.parse(result.design.spec).language == {"Arabic": "ar", "English": "en"}[language]
    if language == "Arabic":
        assert "language ar" in result.design.spec
    assert result.check == run_check(result.design.spec, source.analysis.columns, source.result)


def test_explanation_numbers_must_exist():
    columns, data = gender_share()
    data.rows[0][3], data.rows[1][3] = 61.6, 38.4
    source = report(columns, data)
    bad = "The share is 99%. A donut shows the parts."
    good = "The share is 61.6%. A donut shows the parts."

    def drive(messages, info):
        if not retries(messages):
            return tool_call("deliver_design", spec=DONUT, explanation=bad)
        assert retries(messages)[-1].content == summary_numbers_exist(bad, data).message
        return tool_call("deliver_design", spec=DONUT, explanation=good)

    result = run(source, FunctionModel(drive))
    assert result.design.explanation == good and result.requests == 2 and result.warnings == []
    question_source = report(columns, data, question="Share by gender for people over 25?")
    result = run(question_source, TestModel(call_tools=[], custom_output_args={
        "spec": DONUT, "explanation": "Shares for people over 25. A donut shows the parts.",
    }))
    assert result.design is not None and result.requests == 1 and result.warnings == []


def test_summary_is_not_evidence_for_explanation_numbers():
    source = report(*gender_share(), summary="A mistaken 99% claim.")
    result = run(source, TestModel(call_tools=[], custom_output_args={
        "spec": DONUT, "explanation": "The share is 99%. A donut shows the parts.",
    }))
    assert result.design is None and len(result.warnings) == 1
    assert "99" in result.warnings[0] and result.requests == 2


def test_delivery_combines_failures():
    def drive(messages, info):
        if not retries(messages):
            return tool_call("deliver_design", spec=DONUT, explanation="The share is 99%.")
        message = retries(messages)[-1].content
        assert "Write the title in Arabic." in message and "99" in message
        return tool_call("deliver_design", spec=ARABIC_DONUT,
                         explanation="يوضح الرسم الحصة حسب الجنس. يقارن الرسم الحلقي أجزاء الكل.")

    result = run(report(*gender_share(), language="Arabic"), FunctionModel(drive))
    assert result.design is not None and result.requests == 2 and result.warnings == []


def test_clarification_path():
    def drive(messages, info):
        return tool_call("ask_clarification", question="Which colors can I use?", reason="The colors lack contrast.")

    result = run(report(*gender_share()), FunctionModel(drive))
    assert result.clarification.question == "Which colors can I use?" and result.design is None
    assert result.check is None and result.requests == 1


@pytest.mark.parametrize("language", ["English", "Arabic"])
@pytest.mark.parametrize("row_count", [0, 5])
def test_empty_result_short_circuits(language, row_count):
    columns, _ = gender_share()
    data = table(columns, [])
    data.row_count = row_count

    def drive(messages, info):
        pytest.fail("Empty results must never call the model")

    result = run(report(columns, data, language=language), FunctionModel(drive))
    assert result.clarification.question == EMPTY_RESULT[language]
    assert result.clarification.reason == "The result is empty."
    assert result.requests == 0 and result.check_calls == 0 and result.model is None


def test_a_model_that_repeats_recommend_charts_is_stopped_at_the_fourth_request():
    offered = []

    def drive(messages, info):
        offered.append([t.name for t in info.function_tools])
        return tool_call("recommend_charts", intent="share")

    result = run(report(*gender_share()), FunctionModel(drive))
    assert result.design is None and result.requests == 4
    assert "exceeded max retries" in result.warnings[0]
    assert "recommend_charts" in offered[1] and "recommend_charts" not in offered[2]


def test_a_second_identical_call_is_accepted_and_then_the_tool_is_withdrawn():
    offered = []

    def drive(messages, info):
        offered.append([t.name for t in info.function_tools])
        if len(offered) <= 2:
            return tool_call("recommend_charts", intent="share")
        assert "recommend_charts" not in offered[-1]
        if len(offered) == 3:
            assert last_return(messages).model_response_object()["intent"] == "share"
            return tool_call("check_spec", spec=DONUT)
        return tool_call("deliver_design", spec=DONUT, explanation=EXPLANATION)

    result = run(report(*gender_share()), FunctionModel(drive))
    assert result.design is not None and result.requests == 4 and result.warnings == []


def test_recommend_charts_is_withdrawn_after_two_intents():
    offered = []

    def drive(messages, info):
        offered.append([t.name for t in info.function_tools])
        if len(offered) == 1:
            return tool_call("recommend_charts", intent="share")
        if len(offered) == 2:
            assert "recommend_charts" in offered[-1]
            return tool_call("recommend_charts", intent="compare")
        assert "recommend_charts" not in offered[-1] and "check_spec" in offered[-1]
        if len(offered) == 3:
            return tool_call("check_spec", spec=DONUT)
        return tool_call("deliver_design", spec=DONUT, explanation=EXPLANATION)

    result = run(report(*gender_share()), FunctionModel(drive))
    assert result.design is not None and result.design.intent == "compare"
    assert result.requests == 4 and result.warnings == []


def test_two_recommendations_in_one_response_past_the_budget_get_one_retry():
    calls = []

    def drive(messages, info):
        calls.append(1)
        if len(calls) == 1:
            return tool_call("recommend_charts", intent="share")
        if len(calls) == 2:
            return ModelResponse(parts=[ToolCallPart(tool_name="recommend_charts", args={"intent": "compare"}),
                                        ToolCallPart(tool_name="recommend_charts", args={"intent": "trend"})])
        if len(calls) == 3:
            retry = [p for p in messages[-1].parts if isinstance(p, RetryPromptPart)]
            assert retry and "recommendation calls" in retry[0].model_response()
            return tool_call("check_spec", spec=DONUT)
        return tool_call("deliver_design", spec=DONUT, explanation=EXPLANATION)

    result = run(report(*gender_share()), FunctionModel(drive))
    assert result.design is not None and result.design.intent == "compare" and result.warnings == []


def test_check_spec_is_withdrawn_after_three_calls():
    calls = []

    def drive(messages, info):
        calls.append(1)
        if len(calls) == 1:
            return tool_call("recommend_charts", intent="share")
        if len(calls) <= 4:
            return tool_call("check_spec", spec=DONUT)
        assert "check_spec" not in [t.name for t in info.function_tools]
        return tool_call("deliver_design", spec=DONUT, explanation=EXPLANATION)

    result = run(report(*gender_share()), FunctionModel(drive))
    assert result.design is not None
    assert result.check_calls == 3
    assert result.requests == 5
    assert result.warnings == []


@pytest.mark.parametrize("starting_requests", [None, 7])
def test_request_cap(starting_requests, monkeypatch):
    monkeypatch.setattr("vis_agent.designer.agent.MAX_CHECK_CALLS", 100)

    def drive(messages, info):
        return tool_call("check_spec", spec=DONUT)

    usage = RunUsage(requests=starting_requests) if starting_requests is not None else None
    result = run(report(*gender_share()), FunctionModel(drive), usage=usage)
    assert result.design is None and len(result.warnings) == 1
    assert "request_limit" in result.warnings[0] and result.requests == MAX_REQUESTS
    if usage is not None:
        assert usage.requests == starting_requests + MAX_REQUESTS


def test_suggested_chart_reaches_the_rules():
    def drive(messages, info):
        returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
        if not returns:
            return tool_call("recommend_charts", intent="trend")
        first = last_return(messages).model_response_object()["candidates"][0]
        assert first["name"] == "line" and any(s["rule"] == "S2" for s in first["breakdown"])
        return tool_call("deliver_design", spec="vis line\ntitle Monthly visits\ndescription Visits over time\n"
                         "bind\n  time month\n  value visits\nsort none\n", explanation="Visits change over time. A line shows the trend.")

    result = run(report(*monthly(12)), FunctionModel(drive), brief=DataBrief(suggested_chart_type="line"))
    assert result.design.chart == "line" and result.warnings == []


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


def test_a_spent_check_budget_with_no_pass_ends_in_a_clarification():
    one_colour = DONUT + "palette\n  - #007bff\n"  # two slices, one colour: C6 fails every time
    calls = []

    def drive(messages, info):
        calls.append(1)
        if len(calls) <= 3:
            return tool_call("check_spec", spec=one_colour)
        assert "check_spec" not in [t.name for t in info.function_tools]
        return tool_call("deliver_design", spec=one_colour, explanation=EXPLANATION)

    result = run(report(*gender_share()), FunctionModel(drive))
    assert result.design is None and result.clarification is not None
    assert result.clarification.question.startswith("I could not find a chart that passes")
    assert "C6" in result.clarification.question and "C6" in result.clarification.reason
    assert result.check_calls == 3 and result.warnings == []


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
        return ModelResponse(parts=[ToolCallPart(tool_name="ask_clarification",
                                                 args={"question": "Which?", "reason": "Checking."})])

    for previous, expected in ((None, False), (PreviousDesign(spec="vis donut\n", change="Blue"), True),
                               (PreviousDesign(spec=None, change="Make it an indicator"), True)):
        prompt = build_prompt(source, None, previous=previous)
        deps = DesignerDeps(report=source, prompt=prompt, suggested=None)
        with designer.override(model=FunctionModel(drive)):
            asyncio.run(designer.run(prompt_json(prompt), deps=deps))
        assert ("Answers and revisions" in seen["instructions"]) is expected


def test_numbers_the_caller_wrote_are_wording_not_claims():
    from tests.designer.conftest import gender_share
    from vis_agent.designer.agent import DesignerDeps, build_prompt, wording_context
    from vis_agent.designer.models import PreviousDesign
    from vis_agent.models import QuestionAnswer

    source = report(*gender_share())
    plain = DesignerDeps(report=source, prompt=build_prompt(source, None), suggested=None)
    assert "2026" not in wording_context(plain)
    revised = DesignerDeps(report=source, suggested=None, prompt=build_prompt(
        source, None, clarifications=[QuestionAnswer(question="Which threshold?", answer="income above 60000")],
        previous=PreviousDesign(spec="vis donut\n", change="Change the title to: sales of cities in 2026")))
    context = wording_context(revised)
    assert "2026" in context and "60000" in context and source.question in context
