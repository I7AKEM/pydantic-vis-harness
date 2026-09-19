"""Desired behaviour for three gaps in tests/requests/test_lead_gaps.py. Each is xfail until its candidate patch
(docs/experiments/2026-09-19-patches/) is applied; run with --runxfail after applying a patch."""

import asyncio

import pytest
from pydantic_ai import capture_run_messages
from pydantic_ai.models.function import FunctionModel

from vis_agent.analyst.source import load_csv_report
from vis_agent.designer.agent import create_designer, design_chart
from vis_agent.designer.resolve import resolve
from vis_agent.designer.syntax import parse
from vis_agent.requests.service import requests_of

from .conftest import SALES, call, finish, tool_returns
from .test_lead_gaps import returns_of, stuck_request

PATCHES = "docs/experiments/2026-09-19-patches"


@pytest.mark.xfail(strict=True, reason=f"{PATCHES}/1-check-spec-required-columns.patch")
def test_check_spec_reports_the_missing_required_column(store):
    ds = store.save_upload("wealth.csv", b"gender,wealthy_count,rest_count\nF,37438,150334\nM,37439,149573\n").dataset_id
    report = load_csv_report(store, ds, "Donut per gender")
    spec = "vis donut\ntitle Wealthy by gender\ndescription Two slices\nbind\n  category gender\n  value wealthy_count\n"
    seen = {}

    def drive(messages, info):
        returned = tool_returns(messages)
        if not returned:
            return call("check_spec", spec=spec)
        seen["check"] = returned[0].model_response_object()
        return call("deliver_design", spec="vis table\ntitle Wealth\ndescription All columns\n", explanation="table")

    designer = create_designer("test")
    with capture_run_messages(), designer.override(model=FunctionModel(drive)):
        asyncio.run(design_chart(report, designer, None, required_columns=["gender", "wealthy_count", "rest_count"]))
    assert seen["check"]["ok"] is False
    assert any(v["rule"] == "required_columns" and "rest_count" in v["message"] for v in seen["check"]["violations"])


@pytest.mark.xfail(strict=True, reason=f"{PATCHES}/3-draw-supersedes-a-request-left-by-an-earlier-run.patch")
def test_new_turn_can_draw_after_an_earlier_run_left_a_request_running(deps, dataset_id, agents, store):
    lead = agents[-1]
    stuck = stuck_request(deps, dataset_id, lead)[0]
    other = store.save_upload("other.csv", SALES).dataset_id

    def drive(messages, info):
        if not tool_returns(messages):
            return call("draw", dataset_id=other, question="A different question")
        return finish("Opened.")

    with capture_run_messages() as messages, lead.override(model=FunctionModel(drive)):
        lead.run_sync("Draw again", deps=deps, conversation_id="chat-1")
    opened = returns_of(messages, "draw")[0]
    assert "already active" not in opened and "request_id" in opened
    assert requests_of(deps).get_request(stuck.request_id).status == "stopped"


def test_same_run_still_cannot_redraw_to_bypass_a_diagnostic(deps, dataset_id, agents, store):
    """The guard's purpose stays: one run may not open a second request while its first is running."""
    lead = agents[-1]
    other = store.save_upload("other.csv", SALES).dataset_id

    def drive(messages, info):
        returned = tool_returns(messages)
        if not returned:
            return call("draw", dataset_id=dataset_id, question="First")
        if len(returned) == 1:
            return call("draw", dataset_id=other, question="Second")
        return finish("Blocked.")

    with capture_run_messages() as messages, lead.override(model=FunctionModel(drive)):
        lead.run_sync("Draw", deps=deps, conversation_id="chat-1")
    assert "already active in this conversation" in returns_of(messages, "draw")[1]


@pytest.mark.xfail(strict=True, reason=f"{PATCHES}/4-time-axis-chronological.patch")
def test_a_numeric_year_bound_as_time_is_drawn_in_year_order(store):
    ds = store.save_upload("years.csv", b"year,amount\n2021,5\n2022,9\n2023,7\n2024,8\n").dataset_id
    report = load_csv_report(store, ds, "Amount over the years")
    spec = "vis line\ntitle Trend\ndescription Yearly amounts\nbind\n  time year\n  value amount\n"
    resolved = resolve(parse(spec), report.analysis.columns, report.result)
    assert [row["time"] for row in resolved.config["data"]] == [2021, 2022, 2023, 2024]
