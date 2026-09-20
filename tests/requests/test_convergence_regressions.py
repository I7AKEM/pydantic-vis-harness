"""Regressions from real prepared-CSV runs, without spending model calls."""

import asyncio

import pytest
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.messages import RetryPromptPart

from tests.requests.conftest import CHART_SPEC, call, finish, prompt_of, request_id_of, reviewer_finding, tool_returns
from vis_agent.designer.models import DesignReport
from vis_agent.requests.models import Caller
from vis_agent.requests.service import create_request, run_request


def test_partial_annotations_preserve_columns_values_and_provenance(deps, dataset_id, agents, fake_models, fake_render):
    def annotate_subset(messages, info):
        returned = tool_returns(messages)
        if not returned:
            return call("draw", dataset_id=dataset_id, question="Show supplied sales")
        request_id = request_id_of(messages)
        if returned[-1].tool_name == "draw":
            return call("design_visualization", request_id=request_id, columns=[
                {"name": "amount", "kind": "measure", "meaning": "Revenue", "unit": "SAR",
                 "source": "invented_source", "aggregate": "sum"},
            ])
        if returned[-1].tool_name == "design_visualization":
            return call("render_visualization", request_id=request_id)
        if returned[-1].tool_name == "render_visualization":
            return call("review_visualization", request_id=request_id)
        if returned[-1].tool_name == "review_visualization":
            return call("publish_visualization", request_id=request_id)
        return finish()

    with agents[-1].override(model=FunctionModel(annotate_subset)):
        agents[-1].run_sync("Show sales", deps=deps, conversation_id="partial-columns")
    request = deps.requests.get_request(deps.requests.list_requests()[0].request_id)
    artifact = deps.requests.get_artifact(request.artifact_id)
    assert artifact.report.result.rows == [["East", 10], ["West", 20]]
    region, amount = artifact.report.analysis.columns
    assert (region.name, region.meaning, region.source) == ("region", "region", "region")
    assert (amount.meaning, amount.unit, amount.source, amount.aggregate) == ("Revenue", "SAR", "amount", "none")
    assert fake_models[1].runs == 1


def test_failed_visual_repair_cannot_restart_initial_design_budget(
        deps, dataset_id, agents, reviewer, fake_models, fake_render, monkeypatch):
    from vis_agent import lead as module

    real_design = module.design_chart
    design_calls = 0

    async def fail_repair(report, *args, **kwargs):
        nonlocal design_calls
        design_calls += 1
        if design_calls == 2:
            return DesignReport(dataset_id=report.dataset_id, question=report.question,
                                language=report.language, warnings=["Repair failed"],
                                created_at=report.created_at, seconds=0)
        return await real_design(report, *args, **kwargs)

    def drive(messages, info):
        returned = tool_returns(messages)
        request_id = request_id_of(messages)
        if not returned:
            return call("resume", request_id=request_id)
        last = returned[-1]
        if last.tool_name == "resume":
            return call("design_visualization", request_id=request_id)
        if last.tool_name == "design_visualization":
            if design_calls == 1:
                return call("render_visualization", request_id=request_id)
            if last.outcome != "failed":
                return call("design_visualization", request_id=request_id, direction="Try as a fresh design")
            assert "does not start a new initial design" in last.content
            return call("publish_visualization", request_id=request_id, no_chart_reason="The visual repair failed.")
        if last.tool_name == "render_visualization":
            return call("review_visualization", request_id=request_id)
        if last.tool_name == "review_visualization":
            return call("design_visualization", request_id=request_id, direction="Fix the visible label clipping")
        return finish()

    monkeypatch.setattr(module, "design_chart", fail_repair)
    request = create_request(deps, type="new", dataset_id=dataset_id, question="Show sales",
                             caller=Caller(kind="agent", conversation_id="repair-regression"))
    with reviewer.override(model=FunctionModel(reviewer_finding())), agents[-1].override(model=FunctionModel(drive)):
        result = asyncio.run(run_request(deps, request.request_id))
    saved = deps.requests.get_request(request.request_id)
    assert design_calls == 2 and saved.visual_repair_attempts == 1
    assert len(fake_render) == 1
    assert result.artifact.no_chart_reason == "The visual repair failed."
    assert result.artifact.png_url is None and result.artifact.chart is None
    assert result.artifact.rows == [["East", 10], ["West", 20]]


def test_geometry_only_failure_is_saved_and_repeated_draw_does_not_start_over(deps, dataset_id, agents, fake_models):
    source = deps.store.save_upload("paths.csv", b'path_wkt\n"LINESTRING (46 24, 47 25)"\n')
    ids = []

    def drive(messages, info):
        returned = tool_returns(messages)
        if not returned:
            return call("draw", dataset_id=source.dataset_id, question="Show the delivery routes instead")
        result = returned[-1].model_response_object()
        if len(ids) == 2:
            assert result["dataset_id"] == dataset_id and result["table"]["row_count"] == 2
            return finish("The new sales CSV is available.")
        assert result["terminal"] and result["status"] == "failed"
        assert "WKT" in result["error"]
        assert "LINESTRING" not in result["error"]
        ids.append(result["request_id"])
        if len(ids) == 1:
            return call("draw", dataset_id=source.dataset_id, question="Draw routes")
        return call("draw", dataset_id=dataset_id, question="Read supplied sales")

    with agents[-1].override(model=FunctionModel(drive)):
        agents[-1].run_sync("Draw routes", deps=deps, conversation_id="geometry-only")
    assert ids[0] == ids[1]
    assert len(deps.requests.list_requests()) == 2
    assert fake_models[0] == {"profiler": 0, "analyst": 0}
    assert fake_models[1].runs == fake_models[2].runs == 0


def test_final_promise_after_render_returns_control_to_lead_to_finish(deps, dataset_id, agents, fake_models, fake_render):
    promises = 0

    def drive(messages, info):
        nonlocal promises
        returned = tool_returns(messages)
        if not returned:
            return call("draw", dataset_id=dataset_id, question="Show supplied sales")
        request_id = request_id_of(messages)
        last = returned[-1].tool_name
        if last == "draw":
            return call("design_visualization", request_id=request_id)
        if last == "design_visualization":
            return call("render_visualization", request_id=request_id)
        if last == "render_visualization":
            if not any(isinstance(p, RetryPromptPart) for m in messages for p in m.parts):
                promises += 1
                return finish("I will inspect and publish it.")
            return call("review_visualization", request_id=request_id)
        if last == "review_visualization":
            return call("publish_visualization", request_id=request_id)
        return finish("Published.")

    with agents[-1].override(model=FunctionModel(drive)):
        result = agents[-1].run_sync("Show supplied sales", deps=deps, conversation_id="promise-regression")
    assert result.output == "Published." and promises == 1
    request = deps.requests.get_request(deps.requests.list_requests()[0].request_id)
    assert request.status == "done" and request.artifact_id
    assert fake_models[1].runs == 1 and len(fake_render) == 1


def test_render_resolution_failure_is_a_diagnostic_not_an_unhandled_exception(
        deps, dataset_id, agents, fake_models, fake_render, monkeypatch):
    from vis_agent import lead as module
    from vis_agent.designer.resolve import ResolveError

    def failing_renderer(*args, **kwargs):
        raise ResolveError("The bound measurement is not numeric")

    def drive(messages, info):
        returned = tool_returns(messages)
        if not returned:
            return call("draw", dataset_id=dataset_id, question="Show supplied sales")
        request_id = request_id_of(messages)
        last = returned[-1].tool_name
        if last == "draw":
            return call("design_visualization", request_id=request_id)
        if last == "design_visualization":
            return call("render_visualization", request_id=request_id)
        if last == "render_visualization":
            assert "not numeric" in returned[-1].model_response_object()["specialist_feedback"]["error"]
            return call("publish_visualization", request_id=request_id, no_chart_reason="Renderer rejected the binding.")
        return finish("A source table was delivered; no chart was verified.")

    monkeypatch.setattr(module, "render_design", failing_renderer)
    with agents[-1].override(model=FunctionModel(drive)):
        result = agents[-1].run_sync("Show sales", deps=deps, conversation_id="render-diagnostic")
    assert "no chart was verified" in result.output
    assert not fake_render and fake_models[2].runs == 0


def test_publishing_an_unrenderable_source_returns_terminal_failure_without_argument_retry(deps, agents, fake_models):
    source = deps.store.save_upload("paths.csv", b'path_wkt\n"LINESTRING (46 24, 47 25)"\n')

    def drive(messages, info):
        returned = tool_returns(messages)
        if not returned:
            return call("draw", dataset_id=source.dataset_id, question="Draw routes")
        if returned[-1].tool_name == "draw":
            return call("publish_visualization", request_id=request_id_of(messages),
                        no_chart_reason="The renderer cannot draw raw geometry.")
        result = returned[-1].model_response_object()
        assert result["status"] == "failed" and result["artifact"] is None
        assert "WKT" in result["error"]
        assert not any(isinstance(p, RetryPromptPart) for m in messages for p in m.parts)
        return finish("This renderer cannot draw WKT routes. No chart was produced.")

    with agents[-1].override(model=FunctionModel(drive)):
        result = agents[-1].run_sync("Draw routes", deps=deps, conversation_id="geometry-publish")
    assert result.usage.requests == 3
    assert not deps.requests.list_artifacts()
    assert fake_models[1].runs == fake_models[2].runs == 0


def test_api_resume_of_terminal_source_error_uses_no_more_model_calls(deps, agents, fake_models):
    source = deps.store.save_upload("paths.csv", b'path_wkt\n"LINESTRING (46 24, 47 25)"\n')
    request = create_request(deps, type="new", dataset_id=source.dataset_id, question="Draw routes",
                             caller=Caller(kind="agent", conversation_id="geometry-api-resume"))
    lead_calls = 0

    def drive(messages, info):
        nonlocal lead_calls
        lead_calls += 1
        if not tool_returns(messages):
            return call("resume", request_id=request.request_id)
        return finish("This renderer cannot draw WKT routes. No chart was produced.")

    with agents[-1].override(model=FunctionModel(drive)):
        first = asyncio.run(run_request(deps, request.request_id))
        second = asyncio.run(run_request(deps, request.request_id))
    assert first.status == second.status == "failed"
    assert first.error == second.error and "WKT" in second.error
    saved = deps.requests.get_request(request.request_id)
    assert saved.status == "failed" and saved.error == first.error
    assert saved.requests_used == lead_calls == 2
    assert not deps.requests.list_artifacts()
    assert fake_models[1].runs == fake_models[2].runs == 0


def test_cached_source_diagnostic_restores_terminal_state_before_api_resume(deps, agents, fake_models):
    from vis_agent.requests.service import prepare_request

    source = deps.store.save_upload("paths.csv", b'path_wkt\n"LINESTRING (46 24, 47 25)"\n')
    request = create_request(deps, type="new", dataset_id=source.dataset_id, question="Draw routes",
                             caller=Caller(kind="agent", conversation_id="geometry-cached-resume"))
    expected = asyncio.run(prepare_request(deps, request))["error"]
    request.status, request.error = "running", None
    deps.requests.save_request(request)

    def forbidden(messages, info):
        raise AssertionError("A cached terminal source error must not start a model run")

    with agents[-1].override(model=FunctionModel(forbidden)):
        result = asyncio.run(run_request(deps, request.request_id))
    saved = deps.requests.get_request(request.request_id)
    assert result.status == saved.status == "failed"
    assert result.error == saved.error == expected
    assert saved.requests_used == 0


def test_partial_share_annotation_preserves_known_denominator(deps, dataset_id, agents, fake_models, fake_render):
    from vis_agent.analyst.models import AnalysisReport, ResultColumn
    from vis_agent.requests.service import prepare_request

    request = create_request(deps, type="new", dataset_id=dataset_id, question="Show supplied percentages",
                             caller=Caller(kind="agent", conversation_id="share-annotation"))
    asyncio.run(prepare_request(deps, request))
    report = AnalysisReport.model_validate(request.steps["analyze"])
    report.analysis.columns[-1] = ResultColumn(name="amount", meaning="Share", kind="share", unit="%",
                                              source="amount", denominator="All residents", partition_by=["region"])
    request.steps["analyze"] = report.model_dump(mode="json")
    deps.requests.save_request(request)

    def drive(messages, info):
        returned = tool_returns(messages)
        if not returned:
            return call("resume", request_id=request.request_id)
        last = returned[-1].tool_name
        if last == "resume":
            return call("design_visualization", request_id=request.request_id,
                        columns=[{"name": "amount", "kind": "share", "meaning": "Residents share"}])
        if last == "design_visualization":
            return call("render_visualization", request_id=request.request_id)
        if last == "render_visualization":
            return call("review_visualization", request_id=request.request_id)
        if last == "review_visualization":
            return call("publish_visualization", request_id=request.request_id)
        return finish()

    with agents[-1].override(model=FunctionModel(drive)):
        result = asyncio.run(run_request(deps, request.request_id))
    artifact = deps.requests.get_artifact(result.artifact.artifact_id)
    share = artifact.report.analysis.columns[-1]
    assert share.meaning == "Residents share"
    assert (share.denominator, share.partition_by, share.unit, share.source) == (
        "All residents", ["region"], "%", "amount",
    )
    assert artifact.report.result.rows == [["East", 10], ["West", 20]]


def test_direct_followup_design_cannot_end_with_a_promise(deps, dataset_id, agents, fake_models, fake_render):
    def inspect_source(messages, info):
        if not tool_returns(messages):
            return call("draw", dataset_id=dataset_id, question="Inspect supplied sales")
        return finish("The supplied table is available.")

    with agents[-1].override(model=FunctionModel(inspect_source)):
        inspected = agents[-1].run_sync("Inspect sales", deps=deps, conversation_id="direct-followup")
    request_id = request_id_of(inspected.all_messages())
    saved = deps.requests.get_request(request_id)
    # A resumable infrastructure failure must not disable completion validation on direct continuation.
    saved.status, saved.error = "failed", "Earlier render interrupted"
    deps.requests.save_request(saved)

    def drive(messages, info):
        last = tool_returns(messages)[-1].tool_name
        if last == "draw":
            return call("design_visualization", request_id=request_id)
        if last == "design_visualization":
            return call("render_visualization", request_id=request_id)
        if last == "render_visualization":
            if not any(isinstance(p, RetryPromptPart) for m in messages for p in m.parts):
                return finish("I will inspect and publish it.")
            return call("review_visualization", request_id=request_id)
        if last == "review_visualization":
            return call("publish_visualization", request_id=request_id)
        return finish("Published.")

    with agents[-1].override(model=FunctionModel(drive)):
        result = agents[-1].run_sync("Now draw it", deps=deps, conversation_id="direct-followup",
                                    message_history=inspected.all_messages())
    assert result.output == "Published."
    saved = deps.requests.get_request(request_id)
    assert saved.status == "done" and saved.artifact_id
    assert fake_models[1].runs == 1 and len(fake_render) == 1


def test_informational_followup_does_not_force_delivery_of_an_old_design(deps, dataset_id, agents, fake_models):
    from tests.requests.conftest import CHART_SPEC
    from vis_agent.designer.models import Design

    def inspect_source(messages, info):
        if not tool_returns(messages):
            return call("draw", dataset_id=dataset_id, question="Inspect supplied sales")
        return finish("The supplied table is available.")

    with agents[-1].override(model=FunctionModel(inspect_source)):
        inspected = agents[-1].run_sync("Inspect sales", deps=deps, conversation_id="informational-followup")
    request = deps.requests.get_request(request_id_of(inspected.all_messages()))
    request.steps["design"] = DesignReport(
        dataset_id=dataset_id, question=request.question, language="English", created_at=request.created_at,
        seconds=0, design=Design(spec=CHART_SPEC, chart="bar", intent=None, considered=["bar"], compromises=[],
                                explanation="Compare the supplied values."),
    ).model_dump(mode="json")
    deps.requests.save_request(request)

    with agents[-1].override(model=FunctionModel(lambda messages, info: finish("A legend identifies series."))):
        result = agents[-1].run_sync("What is a legend?", deps=deps, conversation_id="informational-followup",
                                    message_history=inspected.all_messages())
    assert result.output == "A legend identifies series."
    assert result.usage.requests == 1
    assert deps.requests.get_request(request.request_id).artifact_id is None
    assert fake_models[1].runs == fake_models[2].runs == 0


@pytest.mark.parametrize("owner", ["designer", "renderer"])
def test_visible_label_error_allows_one_supported_presentation_repair_regardless_of_owner(
        deps, dataset_id, agents, reviewer, fake_models, fake_render, owner):
    """A renderer-attributed overlap can be fixed by the designer's supported labels-off option."""
    design_calls = 0
    reviews = 0
    request = create_request(deps, type="new", dataset_id=dataset_id, question="Show supplied sales",
                             caller=Caller(kind="agent", conversation_id=f"label-owner-{owner}"))

    def labels_design(messages, info):
        nonlocal design_calls
        design_calls += 1
        saved = deps.requests.get_request(request.request_id)
        assert "render" not in saved.steps and "review" not in saved.steps
        assert saved.review_feedback is None  # Stale state is invalidated before this specialist call.
        prompt = prompt_of(messages)
        if design_calls == 2:
            assert prompt["review"]["findings"][0]["owner"] == owner
            assert saved.visual_repair_attempts == 1
        labels = "on" if design_calls == 1 else "off"
        return call("deliver_design", spec=CHART_SPEC + f"labels {labels}\n",
                    explanation="Compare the supplied values without overlapping labels.")

    def inspect(messages, info):
        nonlocal reviews
        reviews += 1
        if reviews == 1:
            return reviewer_finding(owner=owner, rule="R-2", message="The value labels overlap the city names.")(
                messages, info)
        return call("deliver_review", summary="Category labels are readable and values remain in the source table.",
                    findings=[])

    def drive(messages, info):
        returned = tool_returns(messages)
        if not returned:
            return call("resume", request_id=request.request_id)
        last = returned[-1].tool_name
        if last == "resume":
            return call("design_visualization", request_id=request.request_id)
        if last == "design_visualization":
            assert returned[-1].outcome != "failed"
            return call("render_visualization", request_id=request.request_id)
        if last == "render_visualization":
            return call("review_visualization", request_id=request.request_id)
        if last == "review_visualization" and reviews == 1:
            return call("design_visualization", request_id=request.request_id,
                        direction="The inspector found value labels overlapping city names. Set labels off.")
        if last == "review_visualization":
            return call("publish_visualization", request_id=request.request_id)
        return finish("Published the inspected chart and complete source table.")

    with agents[2].override(model=FunctionModel(labels_design)), \
            reviewer.override(model=FunctionModel(inspect)), agents[-1].override(model=FunctionModel(drive)):
        result = asyncio.run(run_request(deps, request.request_id))

    saved = deps.requests.get_request(request.request_id)
    assert result.status == "done" and result.artifact.review["verdict"] == "pass"
    assert "labels off" in result.artifact.spec
    assert design_calls == reviews == len(fake_render) == 2
    assert saved.visual_repair_attempts == 1 and len(saved.rounds) == 1
    assert fake_render[0][0].result.rows == fake_render[1][0].result.rows == result.artifact.rows
    assert result.artifact.rows == [["East", 10], ["West", 20]]


@pytest.mark.parametrize(("level", "owner"), [("warning", "renderer"), ("error", "none")])
def test_nonactionable_review_does_not_authorize_another_design(
        deps, dataset_id, agents, reviewer, fake_models, fake_render, level, owner):
    request = create_request(deps, type="new", dataset_id=dataset_id, question="Show supplied sales",
                             caller=Caller(kind="agent", conversation_id="nonactionable-review"))

    def drive(messages, info):
        returned = tool_returns(messages)
        if not returned:
            return call("resume", request_id=request.request_id)
        last = returned[-1]
        if last.tool_name == "resume":
            return call("design_visualization", request_id=request.request_id)
        if last.tool_name == "design_visualization":
            if last.outcome == "failed":
                assert "explicit designer- or renderer-owned error" in last.content
                return call("publish_visualization", request_id=request.request_id)
            return call("render_visualization", request_id=request.request_id)
        if last.tool_name == "render_visualization":
            return call("review_visualization", request_id=request.request_id)
        if last.tool_name == "review_visualization":
            return call("design_visualization", request_id=request.request_id, direction="Change the presentation.")
        return finish("Published with the saved review.")

    with reviewer.override(model=FunctionModel(reviewer_finding(level=level, owner=owner))), \
            agents[-1].override(model=FunctionModel(drive)):
        result = asyncio.run(run_request(deps, request.request_id))
    assert result.status == "done"
    assert fake_models[1].runs == len(fake_render) == 1
    assert deps.requests.get_request(request.request_id).visual_repair_attempts == 0


def test_publish_then_revise_cannot_reset_repairs_in_the_same_lead_run(
        deps, dataset_id, agents, reviewer, fake_models, fake_render):
    from vis_agent.requests.service import REQUEST_LIMIT

    request = create_request(deps, type="new", dataset_id=dataset_id, question="Show supplied sales",
                             caller=Caller(kind="agent", conversation_id="publish-revise-loop"))
    artifact_id = None
    rejected_revisions = 0

    def drive(messages, info):
        nonlocal artifact_id, rejected_revisions
        returned = tool_returns(messages)
        if not returned:
            return call("resume", request_id=request.request_id)
        last = returned[-1]
        if last.tool_name == "resume":
            return call("design_visualization", request_id=request.request_id)
        if last.tool_name == "design_visualization":
            return call("render_visualization", request_id=request.request_id)
        if last.tool_name == "render_visualization":
            return call("review_visualization", request_id=request.request_id)
        if last.tool_name == "review_visualization":
            return call("publish_visualization", request_id=request.request_id)
        if last.tool_name == "publish_visualization":
            artifact_id = last.model_response_object()["artifact"]["artifact_id"]
        else:
            assert last.tool_name == "revise" and last.outcome == "failed"
            assert "already published in this lead run" in last.content
            rejected_revisions += 1
        # Deliberately ignore the diagnostic: the shared framework budget must still terminate us.
        return call("revise", artifact_id=artifact_id, change="Hide the overlapping labels.")

    with reviewer.override(model=FunctionModel(reviewer_finding(owner="renderer"))), \
            agents[-1].override(model=FunctionModel(drive)):
        result = asyncio.run(run_request(deps, request.request_id))

    saved = deps.requests.get_request(request.request_id)
    assert rejected_revisions > 1
    assert result.status == "done" and result.artifact.artifact_id == artifact_id
    assert saved.steps["publication_run_id"]
    assert saved.requests_used == REQUEST_LIMIT
    assert len(deps.requests.list_requests()) == len(deps.requests.list_artifacts()) == 1
    assert fake_models[1].runs == len(fake_render) == 1
    assert result.artifact.rows == [["East", 10], ["West", 20]]


def test_later_user_revision_still_works_after_idempotent_publication(
        deps, dataset_id, agents, fake_models, fake_render):
    from tests.test_agents import complete_lead

    conversation_id = "later-user-revision"
    first_drive = complete_lead("draw", {"dataset_id": dataset_id, "question": "Show sales"})
    with agents[-1].override(model=FunctionModel(first_drive)):
        first = agents[-1].run_sync("Show sales", deps=deps, conversation_id=conversation_id)
    original = deps.requests.get_request(deps.requests.list_requests()[0].request_id)
    publication_run_id = original.steps["publication_run_id"]

    def revise_old_artifact(messages, info):
        current = [message for message in messages if message.run_id != publication_run_id]
        returned = tool_returns(current)
        if not returned:
            return call("publish_visualization", request_id=original.request_id)
        if returned[-1].tool_name == "publish_visualization" and len(returned) == 1:
            return call("revise", artifact_id=original.artifact_id, change="Make it blue")
        request_id = request_id_of(current)
        last = returned[-1].tool_name
        if last == "revise":
            assert returned[-1].outcome != "failed"
            return call("design_visualization", request_id=request_id)
        if last == "design_visualization":
            return call("render_visualization", request_id=request_id)
        if last == "render_visualization":
            return call("review_visualization", request_id=request_id)
        if last == "review_visualization":
            return call("publish_visualization", request_id=request_id)
        return finish("Published the requested blue revision.")

    with agents[-1].override(model=FunctionModel(revise_old_artifact)):
        second = agents[-1].run_sync("Make it blue", deps=deps, conversation_id=conversation_id,
                                    message_history=first.all_messages())
    revised = deps.requests.get_artifact(deps.requests.list_artifacts()[0].artifact_id)
    assert second.output == "Published the requested blue revision."
    assert deps.requests.get_request(original.request_id).steps["publication_run_id"] == publication_run_id
    assert revised.parent_artifact_id == original.artifact_id and revised.version == 2
    assert revised.report.result.rows == [["East", 10], ["West", 20]]
    assert fake_models[1].runs == len(fake_render) == 2


def test_lead_candidate_instructions_are_instance_local(deps):
    from vis_agent.lead import LEAD_INSTRUCTIONS, create_lead

    observed = []

    def inspect_instructions(messages, info):
        observed.append(info.instructions)
        return finish("No chart requested.")

    standard = create_lead("test")
    candidate_text = "A candidate instruction string for offline evaluation only."
    candidate = create_lead("test", instructions=candidate_text)
    with standard.override(model=FunctionModel(inspect_instructions)), \
            candidate.override(model=FunctionModel(inspect_instructions)):
        standard.run_sync("Describe your role", deps=deps)
        candidate.run_sync("Describe your role", deps=deps)
        standard.run_sync("Describe your role", deps=deps)
    assert observed == [LEAD_INSTRUCTIONS.strip(), candidate_text, LEAD_INSTRUCTIONS.strip()]
