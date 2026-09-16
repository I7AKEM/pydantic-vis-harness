"""The lead chooses the team; saved requests do not prescribe a workflow."""

import asyncio
from dataclasses import replace

import pytest
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import UsageLimits

from tests.requests.conftest import call, finish, lead_drive, request_id_of, reviewer_finding, tool_returns
from vis_agent.requests.models import Caller
from vis_agent.requests.service import create_request, latest_unfinished, run_request

CHAT = Caller(kind="chat", conversation_id="chat-1")


def run(awaitable):
    return asyncio.run(awaitable)


def new_request(deps, dataset_id, **kwargs):
    return create_request(deps, type="new", dataset_id=dataset_id, question="Compare regional sales", caller=CHAT, **kwargs)


def test_lead_delivers_the_upstream_table_without_an_analysis_pipeline(deps, dataset_id, fake_models, fake_render):
    request = new_request(deps, dataset_id)
    outcome = run(run_request(deps, request.request_id))
    assert outcome.status == "done" and outcome.artifact.png_url
    assert outcome.artifact.rows == [["East", 10], ["West", 20]]
    assert outcome.artifact.row_count == 2 and outcome.artifact.chart == "bar"
    assert outcome.card and outcome.artifact.artifact_id in outcome.card
    counts, designer, reviewer = fake_models
    assert counts == {"profiler": 0, "analyst": 0}
    assert designer.runs == 1 and reviewer.runs == 0
    assert len(fake_render) == 1


def test_preparing_a_draw_does_not_run_any_specialist(deps, dataset_id, agents, fake_models, fake_render):
    lead = agents[-1]

    def prepare_only(messages, info):
        if not tool_returns(messages):
            return call("draw", dataset_id=dataset_id, question="Compare regional sales")
        context = tool_returns(messages)[-1].model_response_object()
        assert context["request_id"]
        return finish("The CSV is ready for the team.")

    with lead.override(model=FunctionModel(prepare_only)):
        result = lead.run_sync("Show this CSV", deps=deps, conversation_id="chat-1")
    request = deps.requests.get_request(deps.requests.list_requests()[0].request_id)
    assert result.output == "The CSV is ready for the team."
    assert request.artifact_id is None and not fake_render
    assert fake_models[1].runs == fake_models[2].runs == 0
    assert request.caller.conversation_id == "chat-1"


def test_review_returns_feedback_to_the_lead_without_automatic_repair(deps, dataset_id, agents, reviewer, fake_models, fake_render):
    request = new_request(deps, dataset_id)
    observed = []

    def review_then_publish(messages, info):
        returned = tool_returns(messages)
        request_id = request_id_of(messages)
        if not returned:
            return call("resume", request_id=request_id)
        last = returned[-1]
        if last.tool_name == "resume":
            return call("design_visualization", request_id=request_id)
        if last.tool_name == "design_visualization":
            return call("render_visualization", request_id=request_id)
        if last.tool_name == "render_visualization":
            return call("review_visualization", request_id=request_id)
        if last.tool_name == "review_visualization":
            observed.append(last.model_response_object())
            return call("publish_visualization", request_id=request_id)
        return finish()

    with reviewer.override(model=FunctionModel(reviewer_finding())), \
            agents[-1].override(model=FunctionModel(review_then_publish)):
        outcome = run(run_request(deps, request.request_id))
    assert outcome.status == "done" and observed
    assert outcome.artifact.review["verdict"] == "revise"
    assert fake_models[1].runs == 1 and len(fake_render) == 1


def test_only_the_lead_can_choose_a_second_design_after_review(deps, dataset_id, agents, reviewer, fake_models, fake_render):
    request = new_request(deps, dataset_id)
    state = {"repaired": False}

    def repair_once(messages, info):
        returned = tool_returns(messages)
        request_id = request_id_of(messages)
        if not returned:
            return call("resume", request_id=request_id)
        last = returned[-1].tool_name
        if last == "resume":
            return call("design_visualization", request_id=request_id)
        if last == "design_visualization":
            return call("render_visualization", request_id=request_id)
        if last == "render_visualization" and not state["repaired"]:
            return call("review_visualization", request_id=request_id)
        if last == "review_visualization":
            state["repaired"] = True
            return call("design_visualization", request_id=request_id, direction="Increase the title contrast.")
        if last == "publish_visualization":
            return finish()
        # A fresh design must not keep the earlier design's visual verdict.
        saved = deps.requests.get_request(request_id)
        assert "review" not in saved.steps
        return call("publish_visualization", request_id=request_id)

    with reviewer.override(model=FunctionModel(reviewer_finding())), \
            agents[-1].override(model=FunctionModel(repair_once)):
        outcome = run(run_request(deps, request.request_id))
    assert outcome.status == "done" and state["repaired"]
    assert fake_models[1].runs == 2 and len(fake_render) == 2
    assert outcome.artifact.review.get("verdict") != "revise"


def test_resume_reuses_the_preview_instead_of_redesigning(deps, dataset_id, agents, fake_models, fake_render):
    request = new_request(deps, dataset_id)

    def stop_after_preview(messages, info):
        returned = tool_returns(messages)
        request_id = request_id_of(messages)
        if not returned:
            return call("resume", request_id=request_id)
        if returned[-1].tool_name == "resume":
            return call("design_visualization", request_id=request_id)
        if returned[-1].tool_name == "design_visualization":
            return call("render_visualization", request_id=request_id)
        return finish("Preview saved.")

    with agents[-1].override(model=FunctionModel(stop_after_preview)):
        run(run_request(deps, request.request_id))
    saved = deps.requests.get_request(request.request_id)
    assert saved.artifact_id is None and "render" in saved.steps
    outcome = run(run_request(deps, request.request_id))
    assert outcome.status == "done" and outcome.artifact.png_url
    assert fake_models[1].runs == 1 and len(fake_render) == 1


def test_publish_and_completed_resume_are_idempotent(deps, dataset_id, agents, fake_models, fake_render):
    request = new_request(deps, dataset_id)
    first = run(run_request(deps, request.request_id))

    def publish_again(messages, info):
        if not tool_returns(messages):
            return call("publish_visualization", request_id=request.request_id)
        assert tool_returns(messages)[-1].model_response_object()["artifact"]["artifact_id"] == first.artifact.artifact_id
        return finish()

    with agents[-1].override(model=FunctionModel(publish_again)):
        agents[-1].run_sync("Show the delivered chart again", deps=deps)
    again = run(run_request(deps, request.request_id))
    assert again.artifact.artifact_id == first.artifact.artifact_id
    assert len(deps.requests.list_artifacts(dataset_id=dataset_id)) == 1
    assert fake_models[1].runs == 1 and len(fake_render) == 1


def test_style_revision_reuses_source_values_and_links_artifacts(deps, dataset_id, fake_models, fake_render):
    first_request = new_request(deps, dataset_id)
    first = run(run_request(deps, first_request.request_id)).artifact
    revision = create_request(deps, type="revise", dataset_id=dataset_id, question="Make it blue", caller=CHAT,
                              parent_artifact_id=first.artifact_id)
    second = run(run_request(deps, revision.request_id)).artifact
    assert second.version == 2 and second.parent_artifact_id == first.artifact_id
    assert second.change == "Make it blue" and second.rows == first.rows
    assert fake_models[0] == {"profiler": 0, "analyst": 0}
    assert fake_models[1].runs == 2


def test_latest_unfinished_never_crosses_conversations(deps, dataset_id, fake_models, fake_render):
    request = new_request(deps, dataset_id)
    assert latest_unfinished(deps, "chat-1").request_id == request.request_id
    assert latest_unfinished(deps, "another-chat") is None
    assert latest_unfinished(deps, None) is None
    run(run_request(deps, request.request_id))
    assert latest_unfinished(deps, "chat-1") is None


def test_model_request_budget_bounds_a_lead_that_ignores_completion(deps, dataset_id, agents, fake_models, fake_render):
    from pydantic_ai.exceptions import UsageLimitExceeded

    request = new_request(deps, dataset_id)
    calls = []

    def looping(messages, info):
        calls.append(1)
        return call("resume", request_id=request.request_id)

    with agents[-1].override(model=FunctionModel(looping)), pytest.raises(UsageLimitExceeded):
        agents[-1].run_sync("Continue", deps=deps, conversation_id="chat-1", usage_limits=UsageLimits(request_limit=3))
    assert len(calls) == 3 and not fake_render


def test_service_requires_a_configured_lead(deps, dataset_id):
    request = new_request(deps, dataset_id)
    with pytest.raises((RuntimeError, ValueError), match="lead"):
        run(run_request(replace(deps, lead=None), request.request_id))


def test_an_explicit_analyst_call_invalidates_the_old_preview(deps, dataset_id, agents, fake_models, fake_render):
    from tests.requests.conftest import prompt_of

    request = new_request(deps, dataset_id)
    observed = []

    def filter_east(messages, info):
        if not tool_returns(messages):
            prompt = prompt_of(messages)
            return call("run_query", sql=f'SELECT region, amount FROM {prompt["table"]} WHERE region = \'East\'', columns=[
                {"name": "region", "meaning": "Region", "kind": "category", "source": "region"},
                {"name": "amount", "meaning": "Sales", "kind": "measure", "source": "amount"},
            ])
        return call("deliver_analysis", summary="Supplied sales for East.")

    def filter_after_preview(messages, info):
        returned = tool_returns(messages)
        request_id = request_id_of(messages)
        if not returned:
            return call("resume", request_id=request_id)
        last = returned[-1].tool_name
        if last == "resume":
            return call("design_visualization", request_id=request_id)
        if last == "design_visualization":
            return call("render_visualization", request_id=request_id)
        if last == "render_visualization" and not observed:
            return call("consult_analyst", request_id=request_id, task="The user requests only East; filter region to East.")
        if last == "consult_analyst":
            saved = deps.requests.get_request(request_id)
            assert not {"design", "render", "review"} & saved.steps.keys()
            observed.append(saved.steps["analyze"]["result"]["rows"])
            return call("design_visualization", request_id=request_id)
        if last == "render_visualization":
            return call("publish_visualization", request_id=request_id)
        return finish()

    with agents[1].override(model=FunctionModel(filter_east)), \
            agents[-1].override(model=FunctionModel(filter_after_preview)):
        result = run(run_request(deps, request.request_id))
    assert result.status == "done" and result.artifact.rows == [["East", 10]]
    assert observed == [[["East", 10]]]
    assert fake_models[0]["profiler"] == 0 and len(fake_render) == 2


def test_failed_redesign_cannot_publish_the_obsolete_preview(deps, dataset_id, agents, fake_models, fake_render, monkeypatch):
    from vis_agent import lead as lead_module

    request = new_request(deps, dataset_id)
    design = lead_module.design_chart
    calls = []

    async def fail_second(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("designer disconnected")
        return await design(*args, **kwargs)

    def change_design(messages, info):
        returned = tool_returns(messages)
        request_id = request_id_of(messages)
        if not returned:
            return call("resume", request_id=request_id)
        if returned[-1].tool_name == "design_visualization":
            return call("render_visualization", request_id=request_id)
        return call("design_visualization", request_id=request_id,
                    direction="Draw the source" if len(returned) == 1 else "Use larger labels")

    monkeypatch.setattr(lead_module, "design_chart", fail_second)
    with agents[-1].override(model=FunctionModel(change_design)):
        result = run(run_request(deps, request.request_id))
    saved = deps.requests.get_request(request.request_id)
    assert result.status == "failed" and "designer disconnected" in result.error
    assert "render" not in saved.steps and saved.artifact_id is None
    assert len(fake_render) == 1


def test_column_annotations_change_meanings_without_changing_values(deps, dataset_id, agents, fake_models, fake_render):
    request = new_request(deps, dataset_id)

    def annotate(messages, info):
        returned = tool_returns(messages)
        request_id = request_id_of(messages)
        if not returned:
            return call("resume", request_id=request_id)
        if returned[-1].tool_name == "resume":
            return call("design_visualization", request_id=request_id, columns=[
                {"name": "amount", "meaning": "Revenue", "kind": "measure", "unit": "SAR", "source": "amount"},
                {"name": "region", "meaning": "Sales region", "kind": "geography", "source": "region"},
            ])
        if returned[-1].tool_name == "design_visualization":
            return call("render_visualization", request_id=request_id)
        if returned[-1].tool_name == "render_visualization":
            return call("publish_visualization", request_id=request_id)
        return finish()

    with agents[-1].override(model=FunctionModel(annotate)):
        outcome = run(run_request(deps, request.request_id))
    assert outcome.status == "done" and outcome.artifact.rows == [["East", 10], ["West", 20]]
    assert [c.name for c in outcome.artifact.columns] == ["region", "amount"]
    assert outcome.artifact.columns[1].unit == "SAR"


def test_resume_after_render_crash_reuses_the_saved_design(deps, dataset_id, fake_models, fake_render, monkeypatch):
    from vis_agent import lead as lead_module

    request = new_request(deps, dataset_id)
    render = lead_module.render_design
    calls = []

    def crash_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("render worker interrupted")
        return render(*args, **kwargs)

    monkeypatch.setattr(lead_module, "render_design", crash_once)
    first = run(run_request(deps, request.request_id))
    saved = deps.requests.get_request(request.request_id)
    assert first.status == "failed" and saved.steps["design"]["design"]
    assert "render" not in saved.steps
    second = run(run_request(deps, request.request_id))
    assert second.status == "done" and second.artifact.png_url
    assert fake_models[1].runs == 1 and len(fake_render) == 1 and len(calls) == 2


def test_request_budget_is_shared_with_nested_specialist_and_persists_on_resume(deps, dataset_id, fake_models, fake_render):
    from vis_agent.requests.service import REQUEST_LIMIT

    request = new_request(deps, dataset_id)
    request.requests_used = REQUEST_LIMIT - 2
    deps.requests.save_request(request)
    first = run(run_request(deps, request.request_id))
    saved = deps.requests.get_request(request.request_id)
    assert first.status == "failed" and saved.requests_used == REQUEST_LIMIT
    # Resume and the lead's design decision spend the final two requests; designer cannot start another.
    assert fake_models[1].calls == 0 and not fake_render
    second = run(run_request(deps, request.request_id))
    assert second.status == "failed" and "budget" in second.error
    assert deps.requests.get_request(request.request_id).requests_used == REQUEST_LIMIT
    assert fake_models[1].calls == 0


def test_specialist_uncertainty_returns_to_lead_without_asking_user(deps, dataset_id, agents, fake_models, fake_render):
    request = new_request(deps, dataset_id)
    observed = []

    def uncertain(messages, info):
        return call("ask_clarification", ask="Which presentation measure?", reason="The optional transformation has two interpretations.")

    def consult_then_stop(messages, info):
        returned = tool_returns(messages)
        request_id = request_id_of(messages)
        if not returned:
            return call("resume", request_id=request_id)
        if returned[-1].tool_name == "resume":
            return call("consult_analyst", request_id=request_id, task="Describe the optional transformation.")
        observed.append(returned[-1].model_response_object())
        return finish("I have the specialist's feedback.")

    with agents[1].override(model=FunctionModel(uncertain)), \
            agents[-1].override(model=FunctionModel(consult_then_stop)):
        run(run_request(deps, request.request_id))
    saved = deps.requests.get_request(request.request_id)
    assert observed and saved.steps["specialist_feedback"]["clarification"]
    assert saved.status != "waiting" and saved.pending() is None
    assert fake_models[1].runs == 0 and not fake_render


def test_failed_analyst_is_withdrawn_instead_of_repeated(deps, dataset_id, agents, fake_models, fake_render):
    request = new_request(deps, dataset_id)
    analyst_runs = 0
    lead_calls = 0

    def failing_analyst(messages, info):
        nonlocal analyst_runs
        analyst_runs += 1
        return call("ask_clarification", ask="Which calculation?", reason="The requested calculation is ambiguous.")

    def repeating_lead(messages, info):
        nonlocal lead_calls
        lead_calls += 1
        returned = tool_returns(messages)
        request_id = request_id_of(messages)
        if not returned:
            return call("resume", request_id=request_id)
        if returned[-1].tool_name == "resume":
            return call("consult_analyst", request_id=request_id, task="Calculate a derived result.")
        if lead_calls < 4:
            assert "consult_analyst" not in [tool.name for tool in info.function_tools]
        return finish("The analyst failed; I will not repeat it.")

    with agents[1].override(model=FunctionModel(failing_analyst)), \
            agents[-1].override(model=FunctionModel(repeating_lead)):
        run(run_request(deps, request.request_id))

    saved = deps.requests.get_request(request.request_id)
    assert analyst_runs == 1 and saved.analyst_attempts == 1
    assert saved.analyst_failure


def test_cancellation_preserves_specialist_checkpoints_for_resume(deps, dataset_id, agents, fake_models, fake_render):
    request = new_request(deps, dataset_id)

    async def interrupted_run():
        design_saved = asyncio.Event()

        async def stop_after_design(messages, info):
            returned = tool_returns(messages)
            if not returned:
                return call("resume", request_id=request.request_id)
            if returned[-1].tool_name == "resume":
                return call("design_visualization", request_id=request.request_id)
            design_saved.set()
            await asyncio.Event().wait()

        with agents[-1].override(model=FunctionModel(stop_after_design)):
            running = asyncio.create_task(run_request(deps, request.request_id))
            await asyncio.wait_for(design_saved.wait(), timeout=5)
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running

    run(interrupted_run())
    saved = deps.requests.get_request(request.request_id)
    assert saved.status == "failed" and "interrupted" in saved.error
    assert saved.steps["analyze"]["result"]["rows"] == [["East", 10], ["West", 20]]
    assert saved.steps["design"]["design"] and saved.requests_used > 0
    result = run(run_request(deps, request.request_id))
    assert result.status == "done" and fake_models[1].runs == 1 and len(fake_render) == 1


def test_accounting_storage_error_does_not_leave_request_marked_in_flight(deps, dataset_id, agents, fake_models, fake_render, monkeypatch):
    request = new_request(deps, dataset_id)
    save = deps.requests.save_request
    calls = []

    def fail_final_save(record):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("disk temporarily unavailable")
        return save(record)

    with monkeypatch.context() as patch:
        patch.setattr(deps.requests, "save_request", fail_final_save)
        with agents[-1].override(model=FunctionModel(lambda messages, info: finish("Interrupted."))), \
                pytest.raises(OSError, match="disk temporarily unavailable"):
            run(run_request(deps, request.request_id))
    result = run(run_request(deps, request.request_id))
    assert result.status == "done" and result.artifact.png_url


def test_concurrent_render_and_redesign_cannot_restore_an_obsolete_preview(deps, dataset_id, agents, fake_models, fake_render, monkeypatch):
    import threading

    from tests.requests.conftest import CHART_SPEC
    from vis_agent import lead as lead_module

    request = new_request(deps, dataset_id)

    def design_then_stop(messages, info):
        returned = tool_returns(messages)
        if not returned:
            return call("resume", request_id=request.request_id)
        if returned[-1].tool_name == "resume":
            return call("design_visualization", request_id=request.request_id)
        return finish()

    with agents[-1].override(model=FunctionModel(design_then_stop)):
        run(run_request(deps, request.request_id))
    render_started, release_render = threading.Event(), threading.Event()
    real_render, real_design = lead_module.render_design, lead_module.design_chart

    def slow_render(*args, **kwargs):
        render_started.set()
        assert release_render.wait(timeout=5), "The concurrent test did not release its renderer"
        return real_render(*args, **kwargs)

    async def concurrent():
        design_started = asyncio.Event()

        async def observed_design(*args, **kwargs):
            design_started.set()
            return await real_design(*args, **kwargs)

        async def invoke(name):
            def drive(messages, info):
                if not tool_returns(messages):
                    return call(name, request_id=request.request_id)
                return finish()
            with agents[-1].override(model=FunctionModel(drive)):
                return await agents[-1].run("Use the existing request", deps=deps)

        monkeypatch.setattr(lead_module, "design_chart", observed_design)
        rendering = asyncio.create_task(invoke("render_visualization"))
        assert await asyncio.to_thread(render_started.wait, 5)
        redesigning = asyncio.create_task(invoke("design_visualization"))
        try:
            # The old rendering owns the request until its checkpoint is saved.
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(design_started.wait(), timeout=0.15)
        finally:
            release_render.set()
        await asyncio.gather(rendering, redesigning)

    monkeypatch.setattr(lead_module, "render_design", slow_render)
    changed_spec = CHART_SPEC.replace("title Sales by region", "title Updated sales view")
    with agents[2].override(model=FunctionModel(lambda messages, info: call(
            "deliver_design", spec=changed_spec, explanation="The updated design uses the same supplied values."))):
        run(concurrent())
    saved = deps.requests.get_request(request.request_id)
    assert "Updated sales view" in saved.steps["design"]["design"]["spec"]
    assert "render" not in saved.steps


def test_concurrent_publications_create_one_artifact(deps, dataset_id, agents, fake_models, fake_render, monkeypatch):
    import threading

    request = new_request(deps, dataset_id)

    def preview_then_stop(messages, info):
        returned = tool_returns(messages)
        if not returned:
            return call("resume", request_id=request.request_id)
        if returned[-1].tool_name == "resume":
            return call("design_visualization", request_id=request.request_id)
        if returned[-1].tool_name == "design_visualization":
            return call("render_visualization", request_id=request.request_id)
        return finish()

    with agents[-1].override(model=FunctionModel(preview_then_stop)):
        run(run_request(deps, request.request_id))
    find_artifact = deps.requests.artifact_for_request
    simultaneous_read = threading.Barrier(2)

    def synchronize_read(request_id):
        try:
            simultaneous_read.wait(timeout=0.15)
        except threading.BrokenBarrierError:
            pass  # With serialized publication only one caller can enter this read at a time.
        return find_artifact(request_id)

    monkeypatch.setattr(deps.requests, "artifact_for_request", synchronize_read)

    def publish_once(messages, info):
        if not tool_returns(messages):
            return call("publish_visualization", request_id=request.request_id)
        return finish(tool_returns(messages)[-1].model_response_object()["artifact"]["artifact_id"])

    async def concurrent():
        return await asyncio.gather(agents[-1].run("Publish", deps=deps), agents[-1].run("Publish", deps=deps))

    with agents[-1].override(model=FunctionModel(publish_once)):
        first, second = run(concurrent())
    assert first.output == second.output
    assert len(deps.requests.list_artifacts(dataset_id=dataset_id)) == 1
