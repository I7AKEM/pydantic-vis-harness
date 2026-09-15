import asyncio
from dataclasses import replace
from datetime import timedelta

import duckdb
import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from vis_agent.designer.agent import create_designer
from vis_agent.render.base import RenderFailed
from vis_agent.requests import runner
from vis_agent.requests.models import STEPS, Caller
from vis_agent.requests.runner import answer_request, create_request, latest_unfinished, run_request
from tests.requests.conftest import CHART_SPEC, Counting, analyst_drive, designer_drive, prompt_of, tool_returns

CHAT = Caller(kind="chat", conversation_id="chat-1")


def run(coro):
    return asyncio.run(coro)


def asking_drive(messages, info):
    return ModelResponse(parts=[ToolCallPart(tool_name="ask_clarification",
                                             args={"question": "Which amount?", "reason": "Two amount columns."})])


def test_a_new_request_runs_every_step_and_delivers(deps, dataset_id, fake_models, fake_render):
    request = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
    outcome = run(run_request(deps, request.request_id))
    assert outcome.status == "done" and outcome.clarification is None
    saved = deps.requests.get_request(request.request_id)
    assert list(saved.steps) == list(STEPS) and saved.language == "English"
    assert saved.steps["review"]["status"] == "not_reviewed"
    artifact = outcome.artifact
    assert artifact.version == 1 and artifact.parent_artifact_id is None
    assert artifact.rows == [["West", 20], ["East", 10]] and artifact.row_count == 2
    assert artifact.chart == "bar" and artifact.png_url.startswith("/renders/") and artifact.png_url.endswith("/chart.png")
    assert artifact.summary == "West leads with 20." and fake_render
    full = deps.requests.get_artifact(artifact.artifact_id)
    assert full.lineage.catalogue_version and full.lineage.rules_version and full.review["status"] == "not_reviewed"
    assert saved.revision is None and "analyze_before_revision" not in saved.steps
    assert run(run_request(deps, request.request_id)).artifact.artifact_id == artifact.artifact_id


def test_a_step_that_dies_keeps_the_checkpoints_and_resume_skips_them(deps, dataset_id, fake_models, fake_render, monkeypatch):
    analyst, _designer = fake_models
    real_design = runner.design_chart
    state = {"died": False}

    async def dying(*args, **kwargs):
        if not state["died"]:
            state["died"] = True
            raise RuntimeError("the process died here")
        return await real_design(*args, **kwargs)

    monkeypatch.setattr(runner, "design_chart", dying)
    request = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
    with pytest.raises(RuntimeError):
        run(run_request(deps, request.request_id))
    saved = deps.requests.get_request(request.request_id)
    assert saved.status == "failed" and "analyze" in saved.steps and "design" not in saved.steps
    assert analyst.runs == 1
    outcome = run(run_request(deps, request.request_id))
    assert outcome.status == "done" and analyst.runs == 1 and outcome.artifact.chart == "bar"


def test_a_single_number_reaches_the_designer_and_delivers_an_indicator(deps, dataset_id, fake_models, fake_render, agents):
    _profiler, analyst, designer, _lead = agents
    from pydantic_ai.models.function import FunctionModel

    def one_number(messages, info):
        if not tool_returns(messages):
            prompt = prompt_of(messages)
            return ModelResponse(parts=[ToolCallPart(tool_name="run_query", args={
                "sql": f'SELECT sum(amount) AS total FROM {prompt["table"]}',
                "columns": [{"name": "total", "meaning": "Total sales", "kind": "measure", "source": "amount",
                             "aggregate": "sum"}]})])
        return ModelResponse(parts=[ToolCallPart(tool_name="deliver_analysis", args={"summary": "The total is 30."})])

    spec = "vis indicator\ntitle Total sales\ndescription Total sales across all regions\ncards\n  - value total\n"

    def indicator(messages, info):
        returns = tool_returns(messages)
        if not returns:
            return ModelResponse(parts=[ToolCallPart(tool_name="check_spec", args={"spec": spec})])
        checked = returns[-1].model_response_object()
        assert checked["ok"], checked
        return ModelResponse(parts=[ToolCallPart(tool_name="deliver_design", args={
            "spec": checked["canonical"], "explanation": "The card shows the total sales."})])

    with analyst.override(model=FunctionModel(one_number)), designer.override(model=FunctionModel(indicator)):
        request = create_request(deps, type="new", dataset_id=dataset_id, question="Total amount", caller=CHAT)
        outcome = run(run_request(deps, request.request_id))
    assert outcome.status == "done" and outcome.artifact.chart == "indicator" and outcome.artifact.png_url
    assert outcome.artifact.no_chart_reason is None and outcome.artifact.rows == [[30]]
    assert deps.requests.get_request(request.request_id).steps["design"]["design"]["chart"] == "indicator"
    assert len(fake_render) == 1


@pytest.mark.parametrize("second_revision", [False, True])
def test_a_repaired_scalar_reaches_indicator_design_and_is_not_reanalysed(
    deps, dataset_id, fake_models, fake_render, agents, second_revision,
):
    _profiler, analyst, designer, _lead = agents
    fallback = create_designer("test")
    configured = replace(deps, designer_fallback=fallback)
    spec = "vis indicator\ntitle Total sales\ndescription Sales across all regions\ncards\n  - value total\n"

    def repair_analysis(messages, info):
        prompt = prompt_of(messages)
        if not prompt.get("previous", {}).get("feedback"):
            return analyst_drive(messages, info)
        assert prompt["previous"]["feedback"]["preserve"] == "All regions and sales"
        if not tool_returns(messages):
            return ModelResponse(parts=[ToolCallPart(tool_name="run_query", args={
                "sql": f'SELECT sum(amount) AS total FROM {prompt["table"]}',
                "columns": [{"name": "total", "meaning": "Total sales", "kind": "measure",
                             "source": "amount", "aggregate": "sum"}],
            })])
        return ModelResponse(parts=[ToolCallPart(tool_name="deliver_analysis", args={
            "summary": "The overall total is 30.",
        })])

    def deliver_indicator(messages, info):
        prompt = prompt_of(messages)
        assert prompt["revision"]["reply"] == "The overall total is 30."
        returns = tool_returns(messages)
        if not returns:
            return ModelResponse(parts=[ToolCallPart(tool_name="check_spec", args={"spec": spec})])
        checked = returns[-1].model_response_object()
        assert checked["ok"], checked
        return ModelResponse(parts=[ToolCallPart(tool_name="deliver_design", args={
            "spec": checked["canonical"], "explanation": "The card shows the requested overall total.",
        })])

    def repair_design(messages, info):
        if "revision" not in prompt_of(messages) or second_revision:
            return ModelResponse(parts=[ToolCallPart(tool_name="request_analysis_revision", args={
                "problem": "A grouped table cannot show the requested overall total",
                "requested_change": "Return the overall sum as one row",
                "preserve": "All regions and sales",
            })])
        return deliver_indicator(messages, info)

    analyst_runs, designer_runs, fallback_runs = (
        Counting(repair_analysis), Counting(repair_design), Counting(deliver_indicator),
    )
    with analyst.override(model=FunctionModel(analyst_runs)), \
            designer.override(model=FunctionModel(designer_runs)), \
            fallback.override(model=FunctionModel(fallback_runs)):
        request = create_request(configured, type="new", dataset_id=dataset_id,
                                 question="Show the overall sales total as a KPI", caller=CHAT)
        outcome = run(run_request(configured, request.request_id))

    assert outcome.status == "done" and outcome.artifact.chart == "indicator" and outcome.artifact.png_url
    assert outcome.artifact.rows == [[30]] and outcome.artifact.row_count == 1
    saved = deps.requests.get_request(request.request_id)
    assert saved.steps["analyze_before_revision"]["result"]["row_count"] == 2
    assert saved.steps["analyze"]["result"]["row_count"] == 1
    assert saved.revision is not None and analyst_runs.runs == 2
    # Counting also sees retries without a ToolReturn as starts. The refused
    # second revision consumes two bounded retries before fallback takes over.
    assert designer_runs.runs == (4 if second_revision else 2)
    assert fallback_runs.runs == int(second_revision) and len(fake_render) == 1
    if second_revision:
        assert any("second table revision" in warning for warning in outcome.artifact.warnings)
        assert any("fallback model" in warning for warning in outcome.artifact.warnings)
    else:
        assert any("chart comes from the revised table" in warning for warning in outcome.artifact.warnings)


def test_a_renderer_failure_delivers_the_table(deps, dataset_id, fake_models, monkeypatch):
    def broken(*args, **kwargs):
        raise RenderFailed("Node is missing.")

    monkeypatch.setattr(runner, "render_design", broken)
    request = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
    outcome = run(run_request(deps, request.request_id))
    assert outcome.status == "done" and outcome.artifact.spec and outcome.artifact.png_url is None
    assert "rendered" in outcome.artifact.no_chart_reason and outcome.artifact.rows


def test_a_question_pauses_and_the_answer_reaches_the_analyst(deps, dataset_id, fake_models, fake_render, agents):
    _profiler, analyst, _designer, _lead = agents
    from pydantic_ai.models.function import FunctionModel
    from tests.requests.conftest import analyst_drive

    seen = {}

    def ask_then_answer(messages, info):
        prompt = prompt_of(messages)
        if not prompt.get("clarifications"):
            return asking_drive(messages, info)
        seen["pairs"] = prompt["clarifications"]
        return analyst_drive(messages, info)

    with analyst.override(model=FunctionModel(ask_then_answer)):
        request = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
        paused = run(run_request(deps, request.request_id))
        assert paused.status == "waiting" and paused.clarification.question == "Which amount?"
        saved = deps.requests.get_request(request.request_id)
        pending = saved.pending()
        assert pending.step == "analyze" and "analyze" not in saved.steps
        assert timedelta(hours=23) < pending.deadline - pending.asked_at <= timedelta(hours=24)
        again = run(run_request(deps, request.request_id))
        assert again.status == "waiting" and again.warnings
        done = run(answer_request(deps, request.request_id, "The amount column", "chat"))
    assert done.status == "done" and seen["pairs"] == [{"question": "Which amount?", "answer": "The amount column"}]
    exchange = deps.requests.get_artifact(done.artifact.artifact_id).clarifications[0]
    assert exchange.answer == "The amount column" and exchange.answered_by == "chat"


def test_a_third_question_fails_the_request(deps, dataset_id, fake_models, agents):
    _profiler, analyst, _designer, _lead = agents
    from pydantic_ai.models.function import FunctionModel

    with analyst.override(model=FunctionModel(asking_drive)):
        request = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
        assert run(run_request(deps, request.request_id)).status == "waiting"
        assert run(answer_request(deps, request.request_id, "one", "chat")).status == "waiting"
        outcome = run(answer_request(deps, request.request_id, "two", "chat"))
    assert outcome.status == "failed" and "Which amount?" in outcome.error
    with pytest.raises(ValueError):
        run(answer_request(deps, request.request_id, "three", "chat"))


def test_revise_without_new_analysis_reuses_the_report_and_links_the_version(deps, dataset_id, fake_models, fake_render, agents):
    analyst, _designer = fake_models
    _profiler, _analyst, designer, _lead = agents
    from pydantic_ai.models.function import FunctionModel
    from tests.requests.conftest import designer_drive

    first = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
    v1 = run(run_request(deps, first.request_id)).artifact
    seen = {}

    def revising(messages, info):
        seen["previous"] = prompt_of(messages).get("previous")
        return designer_drive(messages, info)

    with designer.override(model=FunctionModel(revising)):
        second = create_request(deps, type="revise", dataset_id=dataset_id, question="Make it blue", caller=CHAT,
                                parent_artifact_id=v1.artifact_id)
        v2 = run(run_request(deps, second.request_id)).artifact
    assert analyst.runs == 1
    assert seen["previous"]["change"] == "Make it blue" and seen["previous"]["spec"] == v1.spec
    assert v2.version == 2 and v2.parent_artifact_id == v1.artifact_id
    assert v2.question == "Total by region" and v2.change == "Make it blue" and v2.sql == v1.sql
    lineage = [s.artifact_id for s in deps.requests.list_artifacts(artifact_id=v1.artifact_id)]
    assert lineage == [v2.artifact_id, v1.artifact_id]


def test_revise_with_new_analysis_gives_the_analyst_the_previous_sql(deps, dataset_id, fake_models, fake_render, agents):
    _profiler, analyst, _designer, _lead = agents
    from pydantic_ai.models.function import FunctionModel
    from tests.requests.conftest import analyst_drive

    first = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
    v1 = run(run_request(deps, first.request_id)).artifact
    seen = {}

    def revising(messages, info):
        seen["previous"] = prompt_of(messages).get("previous")
        return analyst_drive(messages, info)

    with analyst.override(model=FunctionModel(revising)):
        second = create_request(deps, type="revise", dataset_id=dataset_id, question="Only the East", caller=CHAT,
                                parent_artifact_id=v1.artifact_id, redo_analysis=True)
        v2 = run(run_request(deps, second.request_id)).artifact
    assert "sum(amount)" in seen["previous"]["sql"] and seen["previous"]["change"] == "Only the East"
    assert [c["name"] for c in seen["previous"]["columns"]] == ["region", "total"]
    assert v2.version == 2


def test_latest_unfinished_finds_the_conversation_request(deps, dataset_id, fake_models, fake_render):
    done = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
    run(run_request(deps, done.request_id))
    assert latest_unfinished(deps, "chat-1") is None
    waiting = create_request(deps, type="new", dataset_id=dataset_id, question="Later", caller=CHAT)
    assert latest_unfinished(deps, "chat-1").request_id == waiting.request_id
    assert latest_unfinished(deps, "chat-2") is None
    assert latest_unfinished(deps, None) is None and latest_unfinished(deps, "") is None


def test_the_budget_is_a_plain_failure(deps, dataset_id, fake_models, monkeypatch):
    monkeypatch.setattr(runner, "REQUEST_LIMIT", 0)
    request = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
    outcome = run(run_request(deps, request.request_id))
    assert outcome.status == "failed" and "budget" in outcome.error


def test_runner_needs_the_request_store(store, agents, dataset_id):
    from vis_agent.deps import AppDeps

    profiler, analyst, designer, _lead = agents
    bare = AppDeps(store=store, profiler=profiler, analyst=analyst, designer=designer)
    with pytest.raises(RuntimeError):
        create_request(bare, type="new", dataset_id=dataset_id, question="q", caller=CHAT)


def test_the_budget_holds_across_a_resume(deps, dataset_id, fake_models, fake_render, agents, monkeypatch):
    """A standalone run counts every model request on the request: the profiler's one, the analyst's asking
    turn, then the resumed analyst's two; the designer then finds the budget of four spent."""
    _profiler, analyst, _designer, _lead = agents
    from pydantic_ai.models.function import FunctionModel
    from tests.requests.conftest import analyst_drive

    def ask_then_answer(messages, info):
        if not prompt_of(messages).get("clarifications"):
            return asking_drive(messages, info)
        return analyst_drive(messages, info)

    monkeypatch.setattr(runner, "REQUEST_LIMIT", 4)
    with analyst.override(model=FunctionModel(ask_then_answer)):
        request = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
        assert run(run_request(deps, request.request_id)).status == "waiting"
        assert deps.requests.get_request(request.request_id).requests_used == 2
        outcome = run(answer_request(deps, request.request_id, "The amount column", "chat"))
    assert outcome.status == "failed" and "budget" in outcome.error
    assert deps.requests.get_request(request.request_id).requests_used == 4


def test_a_database_failure_is_a_plain_failure(deps, dataset_id, fake_models, monkeypatch):
    async def broken(*args, **kwargs):
        raise duckdb.Error("boom")

    monkeypatch.setattr(runner, "analyze_dataset", broken)
    request = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
    outcome = run(run_request(deps, request.request_id))
    assert outcome.status == "failed" and outcome.error == "DuckDB could not run this step."
    assert "analyze" not in deps.requests.get_request(request.request_id).steps


def test_a_designer_that_cannot_finish_delivers_the_table(deps, dataset_id, fake_models, fake_render, monkeypatch):
    from vis_agent.designer.models import DesignReport

    async def unfinished(report, designer, brief, **kwargs):
        return DesignReport(dataset_id=report.dataset_id, question=report.question, language=report.language,
                            warnings=["The designer could not finish: it timed out"], seconds=0,
                            created_at=report.created_at)

    monkeypatch.setattr(runner, "design_chart", unfinished)
    request = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
    outcome = run(run_request(deps, request.request_id))
    assert outcome.status == "done" and outcome.artifact.chart is None and outcome.artifact.rows
    assert outcome.artifact.no_chart_reason == "The designer could not finish: it timed out"
    assert not fake_render


def test_a_failed_design_runs_once_more_on_the_fallback_designer(
    deps, dataset_id, fake_models, fake_render, monkeypatch,
):
    from vis_agent.designer.models import DesignReport

    fallback_deps = replace(deps, designer_fallback=deps.designer)
    real_design = runner.design_chart
    calls = []

    async def with_fallback(report, designer, brief, **kwargs):
        calls.append(designer)
        if len(calls) == 1:
            return DesignReport(dataset_id=report.dataset_id, question=report.question, language=report.language,
                                warnings=["The designer could not finish: it timed out"], seconds=0,
                                created_at=report.created_at)
        return await real_design(report, designer, brief, **kwargs)

    monkeypatch.setattr(runner, "design_chart", with_fallback)
    request = create_request(fallback_deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
    outcome = run(run_request(fallback_deps, request.request_id))
    assert outcome.status == "done" and outcome.artifact.chart == "bar"
    assert calls == [deps.designer, fallback_deps.designer_fallback]
    assert len(outcome.artifact.warnings) == 1 and "fallback model" in outcome.artifact.warnings[0]


def test_a_looping_designer_is_cut_short_and_rescued_by_the_fallback(deps, dataset_id, fake_models, fake_render):
    from vis_agent.designer.agent import create_designer

    looping_calls = []

    def looping(messages, info):
        looping_calls.append(1)
        return ModelResponse(parts=[ToolCallPart(tool_name="recommend_charts", args={"intent": "compare"})])

    fallback = create_designer("test")
    rescued = replace(deps, designer_fallback=fallback)
    with deps.designer.override(model=FunctionModel(looping)), fallback.override(model=FunctionModel(designer_drive)):
        request = create_request(rescued, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
        outcome = run(run_request(rescued, request.request_id))
    assert len(looping_calls) == 4  # two shortlists, one unknown-tool retry, then the run ends
    assert outcome.status == "done" and outcome.artifact.chart == "bar"
    assert len(outcome.artifact.warnings) == 1 and "fallback model" in outcome.artifact.warnings[0]
    assert "exceeded max retries" in outcome.artifact.warnings[0]


def test_the_artifact_carries_the_renderers_compromises(deps, dataset_id, fake_models, monkeypatch):
    from vis_agent.designer.models import Compromise
    from vis_agent.render.base import Rendered

    def render(report, design, out_dir, renderer="gptvis"):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "chart.png").write_bytes(b"png")
        return Rendered(png=out_dir / "chart.png", html=out_dir / "chart.html", config=out_dir / "config.json",
                        width=2400, height=1350, seconds=0.1, non_background_share=0.2,
                        compromises=[Compromise(key="bind", message="Dropped 1 rows with null measures.")],
                        drawn_rows=1, folded_rows=0, dropped_rows=1)

    monkeypatch.setattr(runner, "render_design", render)
    request = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
    outcome = run(run_request(deps, request.request_id))
    assert [c.message for c in outcome.artifact.compromises] == ["Dropped 1 rows with null measures."]
    assert deps.requests.get_artifact(outcome.artifact.artifact_id).compromises[0].key == "bind"


def test_a_revision_speaks_the_language_of_the_change(deps, dataset_id, fake_models, fake_render, agents):
    _profiler, _analyst, designer, _lead = agents
    from pydantic_ai.models.function import FunctionModel
    from tests.requests.conftest import designer_drive

    first = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
    v1 = run(run_request(deps, first.request_id)).artifact
    seen = {}

    def revising(messages, info):
        seen["language"] = prompt_of(messages)["language"]
        return designer_drive(messages, info)

    with designer.override(model=FunctionModel(revising)):
        second = create_request(deps, type="revise", dataset_id=dataset_id, question="اجعله أزرق", caller=CHAT,
                                parent_artifact_id=v1.artifact_id)
        run(run_request(deps, second.request_id))
    assert seen["language"] == "Arabic"
    assert deps.requests.get_request(second.request_id).language == "Arabic"


def test_the_designer_can_ask_the_analyst_for_a_revised_table_once(
    deps, dataset_id, fake_models, fake_render, agents,
):
    _profiler, analyst, designer, _lead = agents
    first_sql = f'SELECT region, sum(amount) AS total FROM "{dataset_id}" GROUP BY 1 ORDER BY 2 DESC'
    second_sql = (f'SELECT region, date AS day, sum(amount) AS total FROM "{dataset_id}" '
                  "GROUP BY 1, 2 ORDER BY 1, 2")

    def revise_analysis(messages, info):
        prompt = prompt_of(messages)
        feedback = prompt.get("previous", {}).get("feedback")
        if feedback is None:
            return analyst_drive(messages, info)
        assert feedback["problem"] == "Need one row per region and day"
        if not tool_returns(messages):
            return ModelResponse(parts=[ToolCallPart(tool_name="run_query", args={
                "sql": (f'SELECT region, date AS day, sum(amount) AS total FROM {prompt["table"]} '
                        "GROUP BY 1, 2 ORDER BY 1, 2"),
                "columns": [
                    {"name": "region", "meaning": "Region", "kind": "category", "source": "region"},
                    {"name": "day", "meaning": "Day", "kind": "ordinal", "source": "date"},
                    {"name": "total", "meaning": "Total sales", "kind": "measure", "source": "amount",
                     "aggregate": "sum"},
                ],
            })])
        return ModelResponse(parts=[ToolCallPart(tool_name="deliver_analysis", args={
            "summary": "Two regions on two days.", "assumptions": ["Kept the total."],
        })])

    def revise_design(messages, info):
        prompt = prompt_of(messages)
        if "revision" not in prompt:
            return ModelResponse(parts=[ToolCallPart(tool_name="request_analysis_revision", args={
                "problem": "Need one row per region and day",
                "requested_change": "Add the day",
                "preserve": "The total by region",
            })])
        assert prompt["revision"]["reply"] == "Two regions on two days. Kept the total."
        assert prompt["revision"]["request"]["problem"] == "Need one row per region and day"
        return designer_drive(messages, info)

    analyst_runs, designer_runs = Counting(revise_analysis), Counting(revise_design)
    with analyst.override(model=FunctionModel(analyst_runs)), designer.override(model=FunctionModel(designer_runs)):
        request = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
        outcome = run(run_request(deps, request.request_id))

    assert outcome.status == "done" and outcome.artifact.chart == "bar"
    assert outcome.artifact.rows == [["East", "2026-01-01", 10], ["West", "2026-01-02", 20]]
    assert "asked the analyst to revise the table" in outcome.artifact.warnings[0]
    saved = deps.requests.get_request(request.request_id)
    assert saved.revision.problem == "Need one row per region and day"
    assert saved.steps["analyze_before_revision"]["analysis"]["sql"] == first_sql
    assert saved.steps["analyze"]["analysis"]["sql"] == second_sql
    assert analyst_runs.runs == 2 and designer_runs.runs == 2


def test_a_second_revision_request_is_refused_and_the_fallback_delivers(
    deps, dataset_id, fake_models, fake_render, agents,
):
    _profiler, analyst, designer, _lead = agents
    fallback = create_designer("test")
    rescued = replace(deps, designer_fallback=fallback)

    def revise_analysis(messages, info):
        prompt = prompt_of(messages)
        if prompt.get("previous", {}).get("feedback") and not tool_returns(messages):
            return ModelResponse(parts=[ToolCallPart(tool_name="run_query", args={
                "sql": f'SELECT region, sum(amount) AS total FROM {prompt["table"]} GROUP BY 1 ORDER BY 2 DESC',
                "columns": [
                    {"name": "region", "meaning": "Region", "kind": "category", "source": "region"},
                    {"name": "total", "meaning": "Total sales", "kind": "measure", "source": "amount",
                     "aggregate": "sum"},
                ],
            })])
        if prompt.get("previous", {}).get("feedback"):
            return ModelResponse(parts=[ToolCallPart(tool_name="deliver_analysis", args={
                "summary": "The table is unchanged.", "assumptions": ["Kept the total."],
            })])
        return analyst_drive(messages, info)

    def request_revision(messages, info):
        return ModelResponse(parts=[ToolCallPart(tool_name="request_analysis_revision", args={
            "problem": "Need another table", "requested_change": "Change the shape", "preserve": "The total",
        })])

    def fallback_drive(messages, info):
        # The fallback designer sees the revision round the first designer asked for.
        assert prompt_of(messages)["revision"]["reply"] == "The table is unchanged. Kept the total."
        return designer_drive(messages, info)

    analyst_runs = Counting(revise_analysis)
    with analyst.override(model=FunctionModel(analyst_runs)), \
            designer.override(model=FunctionModel(request_revision)), \
            fallback.override(model=FunctionModel(fallback_drive)):
        request = create_request(rescued, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
        outcome = run(run_request(rescued, request.request_id))

    assert outcome.status == "done" and outcome.artifact.chart == "bar"
    assert analyst_runs.runs == 2
    assert any("designer asked for a second table revision" in warning for warning in outcome.artifact.warnings)
    assert any("fallback model" in warning for warning in outcome.artifact.warnings)


def test_a_revision_the_analyst_cannot_make_keeps_the_first_table(
    deps, dataset_id, fake_models, fake_render, agents,
):
    _profiler, analyst, designer, _lead = agents

    def cannot_revise(messages, info):
        prompt = prompt_of(messages)
        if prompt.get("previous", {}).get("feedback"):
            return ModelResponse(parts=[ToolCallPart(tool_name="ask_clarification", args={
                "question": "Which day?", "reason": "The table cannot support the requested day.",
            })])
        return analyst_drive(messages, info)

    def revise_then_deliver(messages, info):
        prompt = prompt_of(messages)
        if "revision" not in prompt:
            return ModelResponse(parts=[ToolCallPart(tool_name="request_analysis_revision", args={
                "problem": "Need a day", "requested_change": "Add the day", "preserve": "The totals",
            })])
        assert prompt["revision"]["reply"].startswith("The analyst did not revise the table")
        return designer_drive(messages, info)

    with analyst.override(model=FunctionModel(cannot_revise)), designer.override(model=FunctionModel(revise_then_deliver)):
        request = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
        outcome = run(run_request(deps, request.request_id))

    assert outcome.status == "done"
    assert outcome.artifact.rows == [["West", 20], ["East", 10]]
    saved = deps.requests.get_request(request.request_id)
    assert "analyze_before_revision" not in saved.steps
    assert saved.revision is not None


def test_a_crash_after_the_revision_decision_never_revises_again(
    deps, dataset_id, fake_models, fake_render, agents, monkeypatch,
):
    _profiler, _analyst, designer, _lead = agents
    real_analyze = runner.analyze_dataset
    calls = []
    first_reports = []

    async def crash_on_revision(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("crashed after saving the revision")
        report = await real_analyze(*args, **kwargs)
        first_reports.append(report.model_dump(mode="json"))
        return report

    design_runs = []

    def revise_then_deliver(messages, info):
        if not tool_returns(messages):
            design_runs.append(1)
        if len(design_runs) == 1:
            return ModelResponse(parts=[ToolCallPart(tool_name="request_analysis_revision", args={
                "problem": "Need a day", "requested_change": "Add the day", "preserve": "The total",
            })])
        return designer_drive(messages, info)

    monkeypatch.setattr(runner, "analyze_dataset", crash_on_revision)
    with designer.override(model=FunctionModel(revise_then_deliver)):
        request = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
        original = None
        with pytest.raises(RuntimeError, match="crashed after saving"):
            run(run_request(deps, request.request_id))
        saved = deps.requests.get_request(request.request_id)
        assert saved.revision is not None and saved.steps["analyze"] == first_reports[0]
        outcome = run(run_request(deps, request.request_id))

    assert outcome.status == "done" and outcome.artifact.chart == "bar"
    assert len(calls) == 2
