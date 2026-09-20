"""Offline tests of real-runtime optimization, including actual local PNG delivery."""

import hashlib
import json
import re
from copy import deepcopy

import dspy
import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from evals.lead import optimize_runtime as opt
from vis_agent.analyst.agent import create_analyst
from vis_agent.deps import AppDeps
from vis_agent.designer.agent import create_designer
from vis_agent.lead import LEAD_INSTRUCTIONS, create_lead
from vis_agent.profiler.agent import create_profiler
from vis_agent.providers import Team
from vis_agent.reviewer.agent import create_reviewer


def example(tmp_path, name="sample", *, chart=False):
    csv = tmp_path / f"{name}.csv"
    csv.write_text("region,amount\nEast,10\nWest,20\n")
    expected = {"tool": "draw" if chart else "none", "outcome": "artifact" if chart else "text", "max_seconds": 60}
    if chart:
        expected.update(prepared_csv=True, strict_source=True, require_delivery=True, require_render_evidence=True,
                        review_required=True, review_pass_required=True, charts=["bar"],
                        visible_columns=["region", "amount"], forbid_questions=True)
    return dspy.Example(case_id=name,
                        case_input={"csv": str(csv), "brief": {"producer_agent": "data-agent", "raw_question": "Show regional sales."},
                                    "caller_kind": "agent", "caller_identity": "test-data-agent",
                                    "messages": [f"Show supplied regional sales. Attached CSV: [{csv.name}](/datasets/{{dataset_id}}/profile)"]},
                        expectations=[expected], source={"csv_sha256": hashlib.sha256(csv.read_bytes()).hexdigest()})


def text_record(case, *, quality=True, seconds=1):
    return {"name": case["name"], "turns": [{
        "expected": deepcopy(case["turns"][0]), "tool": "none", "tool_ok": True, "outcome_ok": quality,
        "reply": "Done.", "seconds": seconds, "requests_used": 1, "tools_called": [],
        "latency_ok": seconds <= 60,
    }]}


def fake_team(store, requests, instructions):
    lead = create_lead("test", instructions=instructions)
    deps = AppDeps(store=store, requests=requests, lead=lead, profiler=create_profiler("test"),
                   analyst=create_analyst("test"), designer=create_designer("test"),
                   reviewer=create_reviewer("test"))
    return Team("Test", lead, deps)


def test_correct_slow_beats_fast_wrong_but_is_not_a_strict_pass(tmp_path):
    case = opt.runtime_case(example(tmp_path))
    fast_good = opt.score_record(text_record(case), case)
    slow_good = opt.score_record(text_record(case, seconds=100), case)
    fast_wrong = opt.score_record(text_record(case, quality=False), case)
    assert (fast_good["score"], slow_good["score"], fast_wrong["score"]) == (1, 0.5, 0)
    assert fast_good["strict_pass"] and not slow_good["strict_pass"] and not fast_wrong["contract_pass"]
    assert opt.score_record({"turns": []}, case)["score"] == 0


def test_missing_gates_cannot_receive_reward(tmp_path):
    case = opt.runtime_case(example(tmp_path, chart=True))
    assert opt.score_record(text_record(case), case)["score"] == 0


def test_semantic_overlay_does_not_modify_frozen_bank():
    before = (opt.BANK / "cases.json").read_bytes()
    examples = opt.load_examples("train") + opt.load_examples("validation")
    target = next(e for e in examples if e.case_id.endswith("2177430e3e44a9a3"))
    assert "للإناث" in target.expectations[0]["semantic_fidelity"]["forbidden_expansions"]["gender"]["F"]
    assert "semantic_fidelity" not in json.dumps(target.case_input)
    assert (opt.BANK / "cases.json").read_bytes() == before


def test_known_incomplete_metrics_block_optimization_before_external_work(monkeypatch, tmp_path):
    blockers = opt.optimization_blockers(opt.load_examples("train") + opt.load_examples("validation"))
    assert any("28 rendered tasks" in text for text in blockers)
    assert any("false verdicts" in text for text in blockers)
    def forbidden(*args, **kwargs):
        pytest.fail("Incomplete quality metrics must block before a model/team is constructed")
    monkeypatch.setattr(opt, "RuntimeAdapter", forbidden)
    monkeypatch.setattr("sys.argv", ["optimize_runtime", "optimize", "--allow-external", "--out", str(tmp_path / "run")])
    with pytest.raises(SystemExit) as exc:
        opt.main()
    assert exc.value.code == 2 and not (tmp_path / "run").exists()


def test_rollout_budget_prevents_partial_unscored_batches(tmp_path):
    ex = example(tmp_path)
    async def forbidden(*args, **kwargs):
        pytest.fail("No batch may start over budget")
    adapter = opt.RuntimeAdapter(tmp_path / "run", max_rollouts=1, team_factory=fake_team, runner=forbidden)
    with pytest.raises(opt.BudgetExhausted):
        adapter.evaluate([ex, ex], {"lead": "candidate"})
    assert adapter.calls == 0


def test_trial_evidence_and_reflection_do_not_contain_gold_or_raw_context(tmp_path):
    ex = example(tmp_path)
    async def run(case, *args, **kwargs):
        return text_record(case)
    adapter = opt.RuntimeAdapter(tmp_path / "run", team_factory=fake_team, runner=run)
    batch = adapter.evaluate([ex], {"lead": "candidate"}, capture_traces=True)
    assert batch.scores == [1] and adapter.calls == 1
    assert (tmp_path / "run/rollout-0001/sample/case.json").is_file()
    reflected = adapter.make_reflective_dataset({"lead": "candidate"}, batch, ["lead"])
    serialized = json.dumps(reflected)
    assert "expectations" not in serialized and ex.case_input["csv"] not in serialized
    assert "East,10" not in serialized and "source_csv_sha256" not in serialized
    assert LEAD_INSTRUCTIONS != "candidate"


def test_external_failure_is_retained_as_zero_not_dropped(tmp_path):
    async def failed(*args, **kwargs):
        raise OSError("synthetic provider failure")
    adapter = opt.RuntimeAdapter(tmp_path / "run", team_factory=fake_team, runner=failed)
    result = adapter.evaluate([example(tmp_path)], {"lead": "candidate"})
    assert result.scores == [0] and adapter.calls == 1
    assert result.outputs[0]["seconds"] is None and result.outputs[0]["requests"] is None
    assert result.outputs[0]["execution_seconds"] >= 0
    assert result.outputs[0]["unknown_request_turns"] == 1
    assert "synthetic provider failure" in " ".join(result.outputs[0]["diagnostics"])
    assert (tmp_path / "run/rollout-0001/sample/case.json").is_file()


def test_no_overwrite_and_changed_source_fail_closed(tmp_path):
    ex = example(tmp_path)
    adapter = opt.RuntimeAdapter(tmp_path / "run", team_factory=fake_team)
    with pytest.raises(FileExistsError):
        opt.RuntimeAdapter(tmp_path / "run")
    ex.source["csv_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Source CSV changed"):
        adapter.evaluate([ex], {"lead": "candidate"})
    assert adapter.calls == 0


def test_overlay_drift_is_rejected_without_redefining_historical_fingerprint(tmp_path, monkeypatch):
    from evals.lead.run import runtime_fingerprint
    historical = runtime_fingerprint()
    overlay = tmp_path / "contracts.json"
    overlay.write_bytes(opt.CONTRACTS.read_bytes())
    monkeypatch.setattr(opt, "CONTRACTS", overlay)
    adapter = opt.RuntimeAdapter(tmp_path / "run", team_factory=fake_team)
    overlay.write_text(overlay.read_text() + "\n")
    with pytest.raises(RuntimeError, match="contracts changed"):
        adapter.evaluate([example(tmp_path)], {"lead": "candidate"})
    assert adapter.calls == 0 and runtime_fingerprint() == historical


def test_actual_dspy_proposer_is_bounded_without_a_network_call(monkeypatch):
    seen = []
    def predict(self, **kwargs):
        seen.append(kwargs)
        return dspy.Prediction(proposed_instructions="Improved reusable instructions.")
    monkeypatch.setattr(dspy.Predict, "forward", predict)
    propose = opt.make_dspy_proposer(None, max_reflections=1)
    assert propose({"lead": "seed"}, {"lead": []}, ["lead"]) == {"lead": "Improved reusable instructions."}
    assert seen[0]["current_instructions"] == "seed"
    with pytest.raises(opt.BudgetExhausted):
        propose({"lead": "seed"}, {"lead": []}, ["lead"])


def test_reflection_lm_counts_dspy_adapter_fallback_calls(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-unit-test-key")
    monkeypatch.setattr(dspy.LM, "forward", lambda *args, **kwargs: "mocked response")
    lm = opt.reflection_lm("anthropic/claude-sonnet-4.5", max_calls=1)
    assert lm.forward(prompt="test") == "mocked response"
    with pytest.raises(opt.BudgetExhausted):
        lm.forward(prompt="adapter fallback")
    assert lm.calls == 1
    assert lm.request_budget_exhausted


def test_actual_gepa_search_uses_full_runtime_adapter_without_external_models(tmp_path):
    from gepa import optimize
    instructions = []
    def team(store, requests, text):
        instructions.append(text)
        return fake_team(store, requests, text)
    async def run(case, *args, **kwargs):
        return text_record(case, quality=instructions[-1] == "better")
    adapter = opt.RuntimeAdapter(tmp_path / "run", max_rollouts=8, team_factory=team, runner=run)
    result = optimize(seed_candidate={"lead": "seed"}, trainset=[example(tmp_path, "train")],
                      valset=[example(tmp_path, "validation")], adapter=adapter,
                      custom_candidate_proposer=lambda *args: {"lead": "better"},
                      max_metric_calls=4, reflection_minibatch_size=1, seed=7)
    assert result.best_candidate == {"lead": "better"}
    assert result.val_aggregate_scores[result.best_idx] == 1
    assert adapter.calls == 4


def test_actual_gepa_stops_when_reflection_is_exhausted(tmp_path, monkeypatch):
    from gepa import optimize
    proposals = []
    def predict(self, **kwargs):
        proposals.append(kwargs)
        return dspy.Prediction(proposed_instructions="Different but still failing instructions.")
    monkeypatch.setattr(dspy.Predict, "forward", predict)
    async def run(case, *args, **kwargs):
        return text_record(case, quality=False)
    adapter = opt.RuntimeAdapter(tmp_path / "run", max_rollouts=20, team_factory=fake_team, runner=run)
    proposer = opt.make_dspy_proposer(None, max_reflections=1)
    optimize(seed_candidate={"lead": "seed"}, trainset=[example(tmp_path, "train")],
             valset=[example(tmp_path, "validation")], adapter=adapter,
             custom_candidate_proposer=proposer, stop_callbacks=proposer.budget_exhausted,
             max_metric_calls=20, reflection_minibatch_size=1, seed=7, raise_on_exception=True)
    assert len(proposals) == 1
    assert adapter.calls == 3  # Initial validation + parent/child; no wasted parent evaluations.


def test_gepa_reserves_full_validation_and_retains_previous_best(tmp_path, monkeypatch):
    from gepa import optimize
    instructions = []
    def team(store, requests, text):
        instructions.append(text)
        return fake_team(store, requests, text)
    async def run(case, *args, **kwargs):
        return text_record(case, quality=instructions[-1] == "better")
    monkeypatch.setattr(dspy.Predict, "forward", lambda *args, **kwargs:
                        dspy.Prediction(proposed_instructions="better"))
    adapter = opt.RuntimeAdapter(tmp_path / "run", max_rollouts=5, team_factory=team, runner=run)
    proposer = opt.make_dspy_proposer(None, max_reflections=2)
    result = optimize(seed_candidate={"lead": "seed"}, trainset=[example(tmp_path, "train")],
                      valset=[example(tmp_path, "validation")], adapter=adapter,
                      custom_candidate_proposer=proposer,
                      stop_callbacks=opt.optimization_stopper(adapter, proposer, minibatch_size=1, validation_size=1),
                      max_metric_calls=5, reflection_minibatch_size=1, seed=7)
    assert result.best_candidate == {"lead": "better"}
    assert adapter.calls == 4  # The last spare rollout cannot validate another candidate.


def test_real_pydantic_ai_tools_render_and_deliver_png_with_fake_models(tmp_path):
    """No fake RunContext or fake tool results: the agent drives the real tools."""
    observed_instructions = []
    def call(name, **args):
        return ModelResponse(parts=[ToolCallPart(name, args)])
    def lead_model(messages, info):
        observed_instructions.append(info.instructions)
        returned = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
        if not returned:
            prompt = next(p.content for m in messages for p in m.parts if isinstance(p, UserPromptPart))
            dataset_id = re.search(r"/datasets/(ds_[0-9a-f]+)/", prompt).group(1)
            return call("draw", dataset_id=dataset_id, question="Show supplied regional sales.")
        last = returned[-1]
        value = last.model_response_object()
        if last.tool_name == "publish_visualization":
            return ModelResponse(parts=[TextPart(f"Delivered. ![Chart]({value['artifact']['png_url']})")])
        tool = {"draw": "design_visualization", "design_visualization": "render_visualization",
                "render_visualization": "review_visualization", "review_visualization": "publish_visualization"}[last.tool_name]
        args = {"request_id": value["request_id"]}
        if tool == "design_visualization":
            args["direction"] = "Compare the supplied regional sales in a bar chart without recomputing."
        return call(tool, **args)
    def designer_model(messages, info):
        return call("deliver_design", spec="vis bar\ntitle Regional sales\nbind\n  category region\n  value amount",
                    explanation="Compare the supplied regional sales.")
    def reviewer_model(messages, info):
        return call("deliver_review", summary="Labels and values are readable.", findings=[])
    def team(store, requests, instructions):
        configured = fake_team(store, requests, instructions)
        # Use the documented agent.override mechanism; contexts remain active
        # through the awaited real run_case and close in the runner below.
        return configured
    from evals.lead.run import run_case
    async def run(case, lead, profiler, analyst, designer, fallback, evidence, reviewer, **kwargs):
        with lead.override(model=FunctionModel(lead_model)), designer.override(model=FunctionModel(designer_model)), \
                reviewer.override(model=FunctionModel(reviewer_model)):
            return await run_case(case, lead, profiler, analyst, designer, fallback, evidence, reviewer, **kwargs)
    adapter = opt.RuntimeAdapter(tmp_path / "real-run", team_factory=team, runner=run, turn_timeout=15)
    result = adapter.evaluate([example(tmp_path, chart=True)], {"lead": "Candidate instructions for this instance."})
    assert result.scores == [1], result.outputs
    assert all("Candidate instructions for this instance." in text for text in observed_instructions)
    assert list((tmp_path / "real-run").rglob("chart.png"))
