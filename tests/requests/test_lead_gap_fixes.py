"""Desired behaviour for the candidate patches in docs/experiments/2026-09-19-patches/. Each patched test is xfail
until its patch is applied; run with --runxfail after applying a patch. Unmarked tests are guards that must hold
before and after."""

import asyncio

import pytest
from pydantic_ai import capture_run_messages
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import UsageLimits

from vis_agent.analyst.source import load_csv_report
from vis_agent.designer.agent import create_designer, design_chart
from vis_agent.designer.resolve import resolve
from vis_agent.designer.syntax import parse
from vis_agent.requests.service import requests_of

from .conftest import SALES, call, finish, tool_returns
from .test_lead_gaps import returns_of, stuck_request

PATCHES = "docs/experiments/2026-09-19-patches"
WEALTH = b"gender,wealthy_count,rest_count\nF,37438,150334\nM,37439,149573\n"


def designer_run(store, first_spec, required):
    """Run the designer with a check_spec call, then deliver a table. Returns the check result and the retry text."""
    ds = store.save_upload("wealth.csv", WEALTH).dataset_id
    report = load_csv_report(store, ds, "Donut per gender")
    seen = {}

    def drive(messages, info):
        returned = tool_returns(messages)
        if not returned:
            return call("check_spec", spec=first_spec)
        seen["check"] = returned[0].model_response_object()
        return call("deliver_design", spec="vis table\ntitle Wealth\ndescription All columns\n", explanation="table")

    designer = create_designer("test")
    with capture_run_messages(), designer.override(model=FunctionModel(drive)):
        asyncio.run(design_chart(report, designer, None, required_columns=required))
    return seen["check"]


@pytest.mark.xfail(strict=True, reason=f"{PATCHES}/1-check-spec-required-columns.patch")
def test_check_spec_reports_the_missing_required_column(store):
    check = designer_run(store, "vis donut\ntitle Wealthy by gender\ndescription Two slices\nbind\n  category gender\n"
                                "  value wealthy_count\n", ["gender", "wealthy_count", "rest_count"])
    assert check["ok"] is False
    assert any(v["rule"] == "required_columns" and "rest_count" in v["message"] for v in check["violations"])


@pytest.mark.xfail(strict=True, reason=f"{PATCHES}/1-check-spec-required-columns.patch")
def test_check_spec_lists_the_required_column_together_with_other_defects(store):
    """Parity with deliver_design, which already reports both kinds of defect in one message."""
    check = designer_run(store, "vis donut\ntitle Wealthy by gender\ndescription Two slices\nbind\n  category gender\n"
                                "  value wealthy_count\npercent true\n", ["gender", "wealthy_count", "rest_count"])
    rules = {v["rule"] for v in check["violations"]}
    assert check["ok"] is False
    assert "required_columns" in rules and len(rules) >= 2, rules


@pytest.mark.xfail(strict=True, reason=f"{PATCHES}/4-time-axis-chronological.patch")
def test_a_numeric_year_bound_as_time_is_drawn_in_year_order_by_default(store):
    ds = store.save_upload("years.csv", b"year,amount\n2021,5\n2022,9\n2023,7\n2024,8\n").dataset_id
    report = load_csv_report(store, ds, "Amount over the years")
    spec = "vis line\ntitle Trend\ndescription Yearly amounts\nbind\n  time year\n  value amount\n"
    resolved = resolve(parse(spec), report.analysis.columns, report.result)
    assert [row["time"] for row in resolved.config["data"]] == [2021, 2022, 2023, 2024]


def test_an_explicit_value_sort_on_a_time_axis_still_applies(store):
    """Guard: the patch changes only the default; a designer that asks for a value order keeps it."""
    ds = store.save_upload("years.csv", b"year,amount\n2021,5\n2022,9\n2023,7\n2024,8\n").dataset_id
    report = load_csv_report(store, ds, "Amount over the years")
    spec = "vis line\ntitle Trend\ndescription Yearly amounts\nbind\n  time year\n  value amount\nsort value desc\n"
    resolved = resolve(parse(spec), report.analysis.columns, report.result)
    assert [row["time"] for row in resolved.config["data"]] == [2022, 2024, 2023, 2021]


# --- patch 3: explicit cleanup of the requests a run owns ------------------------------------------------------------

P3 = f"{PATCHES}/3-finish-the-requests-a-lead-run-owns.patch"


@pytest.mark.xfail(strict=True, reason=P3)
def test_budget_crash_marks_the_request_failed_and_the_next_draw_proceeds(deps, dataset_id, agents, store):
    lead = agents[-1]
    stuck = stuck_request(deps, dataset_id, lead)[0]
    failed = requests_of(deps).get_request(stuck.request_id)
    assert failed.status == "failed" and "request_limit" in (failed.error or "")
    other = store.save_upload("other.csv", SALES).dataset_id

    def drive(messages, info):
        if not tool_returns(messages):
            return call("draw", dataset_id=other, question="A different question")
        return finish("Opened.")

    with capture_run_messages() as messages, lead.override(model=FunctionModel(drive)):
        lead.run_sync("Draw again", deps=deps, conversation_id="chat-1")
    opened = returns_of(messages, "draw")[0]
    assert "already active" not in opened and "request_id" in opened


@pytest.mark.xfail(strict=True, reason=P3)
def test_a_turn_ending_in_text_stops_its_unpublished_request_and_resume_reactivates_it(deps, dataset_id, agents):
    lead = agents[-1]

    def inspect_only(messages, info):
        if not tool_returns(messages):
            return call("draw", dataset_id=dataset_id, question="What is in this file?")
        return finish("Two regions with amounts.")

    with capture_run_messages() as messages, lead.override(model=FunctionModel(inspect_only)):
        lead.run_sync("What is in this file?", deps=deps, conversation_id="chat-1")
    request_id = tool_returns(messages)[0].model_response_object()["request_id"]
    stopped = requests_of(deps).get_request(request_id)
    assert stopped.status == "stopped" and "resume" in (stopped.error or "")

    def resume_it(messages, info):
        if not tool_returns(messages):
            return call("resume", request_id=request_id)
        return finish("Continuing.")

    with capture_run_messages() as messages, lead.override(model=FunctionModel(resume_it)):
        lead.run_sync("Continue", deps=deps, conversation_id="chat-1")
    assert "request_id" in returns_of(messages, "resume")[0]


def test_cleanup_touches_only_the_requests_the_run_owns(deps, dataset_id, agents):
    """Guard, before and after patch 3: a running request owned by another run (or by nobody, as API-created
    requests are) is left alone by a run that crashes in the same conversation."""
    from vis_agent.requests.models import Caller
    from vis_agent.requests.service import create_request
    foreign = create_request(deps, type="new", dataset_id=dataset_id, question="Someone else's",
                             caller=Caller(kind="chat", conversation_id="chat-2"))
    foreign.steps["lead_run_id"] = "another-run"
    requests_of(deps).save_request(foreign)
    lead = agents[-1]

    def drive(messages, info):
        return call("find_dataset", query="")

    with lead.override(model=FunctionModel(drive)), pytest.raises(UsageLimitExceeded):
        lead.run_sync("Look", deps=deps, conversation_id="chat-2", usage_limits=UsageLimits(request_limit=2))
    assert requests_of(deps).get_request(foreign.request_id).status == "running"
