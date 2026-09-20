"""Finished upstream KPI values are rendered directly and remain unchanged on revision."""

import asyncio

import pytest
from pydantic_ai.models.function import FunctionModel

from tests.requests.conftest import Counting, call, prompt_of
from vis_agent.requests.models import Caller
from vis_agent.requests.service import create_request, run_request

CALLER = Caller(kind="chat", conversation_id="indicator-tests")
SPEC = "vis indicator\ntitle Total sales\ndescription Supplied sales total\ncards\n  - value total\n"


def indicator_design(messages, info):
    previous = prompt_of(messages).get("previous") or {}
    spec = SPEC + ("palette\n  - #1e40af\n" if "blue" in previous.get("change", "") else "")
    return call("deliver_design", spec=spec, explanation="The metric card displays the supplied total.")


@pytest.fixture
def dataset_id(store):
    return store.save_upload("upstream-total.csv", b"total\n30\n").dataset_id


@pytest.fixture
def indicator_models(agents, fake_models):
    designer = agents[2]
    count = Counting(indicator_design)
    with designer.override(model=FunctionModel(count)):
        yield count


def new_indicator(deps, dataset_id):
    request = create_request(deps, type="new", dataset_id=dataset_id, question="Show the sales KPI", caller=CALLER)
    return request, asyncio.run(run_request(deps, request.request_id))


def test_indicator_renders_the_supplied_scalar_without_recalculating(deps, dataset_id, indicator_models, fake_render, fake_models):
    _, result = new_indicator(deps, dataset_id)
    assert result.status == "done" and result.artifact.chart == "indicator"
    assert result.artifact.rows == [[30]] and result.artifact.row_count == 1
    assert fake_models[0] == {"profiler": 0, "analyst": 0}
    assert indicator_models.runs == 1


def test_indicator_style_revision_reuses_values_and_versions(deps, dataset_id, indicator_models, fake_render):
    _, first = new_indicator(deps, dataset_id)
    revision = create_request(deps, type="revise", dataset_id=dataset_id, question="Make it blue", caller=CALLER,
                              parent_artifact_id=first.artifact.artifact_id)
    second = asyncio.run(run_request(deps, revision.request_id))
    assert second.status == "done" and second.artifact.chart == "indicator"
    assert "#1e40af" in second.artifact.spec
    assert second.artifact.sql == first.artifact.sql and second.artifact.rows == [[30]]
    assert second.artifact.version == 2 and second.artifact.parent_artifact_id == first.artifact.artifact_id
    assert indicator_models.runs == 2


@pytest.mark.parametrize("change", ["اجعل البطاقة باللغة العربية", "Make this card Arabic"])
def test_indicator_language_revision_changes_labels_only(deps, dataset_id, indicator_models, fake_render, agents, change):
    from vis_agent.designer.syntax import parse

    _, first = new_indicator(deps, dataset_id)
    translated = ('vis indicator\ntitle إجمالي المبيعات\ndescription إجمالي المبيعات للنطاق المطلوب\n'
                  'language ar\ncards\n  - value total\ncolumnLabels\n  - ["total", "إجمالي المبيعات"]\n')

    def arabic_design(messages, info):
        assert prompt_of(messages)["previous"]["change"] == change
        return call("deliver_design", spec=translated, explanation="تمت ترجمة تسميات البطاقة.")

    revision = create_request(deps, type="revise", dataset_id=dataset_id, question=change,
                              caller=CALLER, parent_artifact_id=first.artifact.artifact_id)
    with agents[2].override(model=FunctionModel(arabic_design)):
        second = asyncio.run(run_request(deps, revision.request_id))
    assert second.artifact.sql == first.artifact.sql and second.artifact.rows == [[30]]
    assert parse(second.artifact.spec).column_labels == {"total": "إجمالي المبيعات"}


def test_completed_indicator_is_not_regenerated_on_resume(deps, dataset_id, indicator_models, fake_render):
    request, first = new_indicator(deps, dataset_id)
    second = asyncio.run(run_request(deps, request.request_id))
    assert second.artifact.artifact_id == first.artifact.artifact_id
    assert indicator_models.runs == 1 and len(fake_render) == 1
