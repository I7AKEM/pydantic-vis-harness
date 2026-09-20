"""Delivery is deterministic: bounded preview, complete result endpoint, honest review status."""

import asyncio
from contextlib import ExitStack
import re

import httpx
import pytest
from pydantic_ai.models.function import FunctionModel
from starlette.applications import Starlette

from vis_agent.analyst.agent import create_analyst
from vis_agent.analyst.models import ResultColumn
from vis_agent.card import CARD_ROWS, LABELS, card
from vis_agent.deps import AppDeps
from vis_agent.designer.agent import create_designer
from vis_agent.lead import create_lead
from vis_agent.models import DisplayLabels
from vis_agent.profiler.agent import create_profiler
from vis_agent.requests.api import add_request_routes
from vis_agent.requests.models import Caller, LEAD_ROWS
from vis_agent.requests.service import create_request, outcome_for, prepare_request, publish
from vis_agent.requests.store import RequestStore


COLUMNS = [ResultColumn(name="batch_code", meaning="Batch identifier", kind="category"),
           ResultColumn(name="reading", meaning="Assay reading", kind="measure")]


@pytest.mark.parametrize("language", ["English", "Arabic"])
def test_complete_result_link_does_not_expand_or_misrepresent_the_preview(language):
    rows = [[f"B{i:03}", i + 0.125] for i in range(73)]
    artifact_id = "art_" + "b" * 32
    display = DisplayLabels(column_labels={"batch_code": "معرّف الدفعة"})
    shown = card(language=language, columns=COLUMNS, rows=rows, row_count=len(rows),
                 png_url="/renders/preview/chart.png", artifact_id=artifact_id, display_labels=display)
    labels = LABELS[language]
    assert f"[{labels['source']}](/artifacts/{artifact_id})" in shown
    assert "![chart](/renders/preview/chart.png)" in shown
    assert labels["rows"].format(shown=CARD_ROWS, total=73) in shown
    assert shown.count("\n| B") == CARD_ROWS
    assert "| B019 | 19.125 |" in shown and "| B020 |" not in shown
    assert "معرّف الدفعة" in shown
    assert "scroll" not in shown.lower()
    assert rows[-1] == ["B072", 72.125]


def test_unpersisted_card_does_not_invent_a_source_link():
    shown = card(language="English", columns=COLUMNS, rows=[["X", 1]], row_count=1)
    assert "/artifacts/" not in shown


@pytest.mark.parametrize("language,uncertainty", [
    ("English", "The compressed legend is not readable enough to verify label-to-color pairing."),
    ("Arabic", "لا تكفي دقة مفتاح الرسم للتحقق من مطابقة الألوان والتسميات."),
])
def test_material_uncertainty_is_visible_and_is_not_an_error_or_pass(language, uncertainty):
    labels = LABELS[language]
    review = {"status": "reviewed", "verdict": "uncertain", "review": {
        "verdict": "uncertain", "summary": "The available image does not establish a defect.",
        "findings": [], "uncertainties": [uncertainty],
    }}
    shown = card(language=language, review=review)
    assert f"**{labels['review']}**: uncertain" in shown
    assert f"**{labels['unverified']}**" in shown and uncertainty in shown
    assert f"**{labels['findings']}**" not in shown
    assert f"**{labels['review']}**: pass" not in shown

    passed = card(language=language, review={"status": "reviewed", "verdict": "pass", "review": {
        "verdict": "pass", "findings": [], "uncertainties": [],
    }})
    assert f"**{labels['review']}**: pass" in passed
    assert labels["unverified"] not in passed and uncertainty not in passed


def test_error_and_remaining_uncertainty_are_both_retained():
    defect = "The axis title uses a different unit from the supplied measurement."
    uncertainty = "The smallest legend label cannot be read."
    shown = card(language="English", review={"status": "reviewed", "verdict": "revise", "review": {
        "findings": [{"level": "error", "message": defect}], "uncertainties": [uncertainty],
    }})
    assert "**Open findings**" in shown and defect in shown
    assert "**Unverified**" in shown and uncertainty in shown


def test_published_card_link_fetches_every_result_row_without_model_requests(store):
    expected = [[f"{i:06}", i + 0.125] for i in range(73)]
    csv = "batch_code,reading\n" + "".join(f"{code},{value}\n" for code, value in expected)
    source = store.save_upload("assay-readings.csv", csv.encode())
    agents = [create_profiler("test"), create_analyst("test"), create_designer("test"), create_lead("test")]
    deps = AppDeps(store=store, profiler=agents[0], analyst=agents[1], designer=agents[2],
                   lead=agents[3], requests=RequestStore(store))
    called = []

    def unexpected_model_request(messages, info):
        called.append(True)
        raise AssertionError("Persisting, displaying, or reading an artifact must not call a model.")

    async def exercise():
        request = create_request(deps, type="new", dataset_id=source.dataset_id,
                                 question="Deliver the unchanged supplied assay readings.",
                                 caller=Caller(kind="agent", identity="upstream-data-agent"))
        await prepare_request(deps, request)
        result = await publish(deps, request, no_chart_reason="Renderer unavailable in this delivery-only test.")
        assert result.artifact is not None and result.card is not None
        assert len(result.artifact.rows) == LEAD_ROWS
        assert result.artifact.row_count == len(expected)
        assert result.card.count("\n| 000") == CARD_ROWS
        assert "20 of 73 rows" in result.card
        match = re.search(r"\]\((/artifacts/art_[0-9a-f]{32})\)", result.card)
        assert match is not None
        app = Starlette()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            add_request_routes(app, deps, agents[3], http=client)
            response = await client.get(match.group(1))
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        full = response.json()
        assert full["artifact_id"] == result.artifact.artifact_id
        assert full["report"]["result"]["columns"] == ["batch_code", "reading"]
        assert full["report"]["result"]["row_count"] == len(expected)
        assert full["report"]["result"]["rows"] == expected
        # Rebuilding or re-publishing a completed card needs neither another model turn nor a new artifact.
        reloaded = await outcome_for(deps, request)
        republished = await publish(deps, request, no_chart_reason="Same delivery, not a new analysis.")
        assert reloaded.card == republished.card == result.card
        assert republished.artifact.artifact_id == result.artifact.artifact_id
        assert request.requests_used == 0

    with ExitStack() as stack:
        for agent in agents:
            stack.enter_context(agent.override(model=FunctionModel(unexpected_model_request)))
        asyncio.run(exercise())
    assert called == []
