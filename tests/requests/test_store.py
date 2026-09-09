import json
import re
from datetime import datetime, timedelta, timezone

import pytest

from vis_agent.analyst.models import AnalysisReport, AnalysisRevision
from vis_agent.requests.models import Artifact, Caller, Exchange, LeadArtifact, Lineage, Request, STEPS
from vis_agent.requests.store import ArtifactNotFound, RequestNotFound, RequestStore
from vis_agent.store import DatasetNotFound

SALES = b"id,region,date,amount\n001,East,2026-01-01,10\n002,West,2026-01-02,20\n"
CHAT = Caller(kind="chat", conversation_id="chat-1")


@pytest.fixture
def requests(store):
    return RequestStore(store)


@pytest.fixture
def dataset_id(store):
    return store.save_upload("sales.csv", SALES).dataset_id


def report(dataset_id, rows=None):
    return AnalysisReport(dataset_id=dataset_id, question="Total by region", language="en", seconds=0,
                          created_at=datetime.now(timezone.utc))


def artifact(requests, request, version=1, parent=None):
    return Artifact(artifact_id=requests.new_artifact_id(), request_id=request.request_id,
                    dataset_id=request.dataset_id, version=version, parent_artifact_id=parent,
                    question="Total by region", report=report(request.dataset_id),
                    lineage=Lineage(catalogue_version="cat1", rules_version="rul1"),
                    created_at=datetime.now(timezone.utc))


def test_new_request_round_trip(requests, dataset_id):
    request = requests.new_request("new", dataset_id, "  Total by region ", CHAT)
    assert re.fullmatch(r"rq_[0-9a-f]{32}", request.request_id)
    assert request.status == "running" and request.question == "Total by region"
    assert requests.get_request(request.request_id) == request


def test_new_request_checks_its_inputs(requests, dataset_id):
    with pytest.raises(DatasetNotFound):
        requests.new_request("new", "ds_" + "0" * 32, "q", CHAT)
    with pytest.raises(ValueError):
        requests.new_request("new", "nonsense", "q", CHAT)
    with pytest.raises(ValueError, match="question"):
        requests.new_request("new", dataset_id, "   ", CHAT)
    with pytest.raises(ValueError, match="artifact"):
        requests.new_request("revise", dataset_id, "Make it blue", CHAT)
    with pytest.raises(ValueError, match="revision"):
        requests.new_request("new", dataset_id, "q", CHAT, parent_artifact_id="art_" + "0" * 32)


def test_a_revision_must_name_an_artifact_of_the_same_dataset(requests, store, dataset_id):
    other = store.save_upload("other.csv", SALES).dataset_id
    first = requests.new_request("new", dataset_id, "Total by region", CHAT)
    saved = requests.save_artifact(artifact(requests, first))
    with pytest.raises(ValueError, match="another dataset"):
        requests.new_request("revise", other, "Make it blue", CHAT, parent_artifact_id=saved.artifact_id)
    revision = requests.new_request("revise", dataset_id, "Make it blue", CHAT, parent_artifact_id=saved.artifact_id)
    assert revision.parent_artifact_id == saved.artifact_id


def test_save_request_keeps_steps_and_bumps_updated_at(requests, dataset_id):
    request = requests.new_request("new", dataset_id, "q", CHAT)
    before = request.updated_at
    request.steps["understand"] = {"language": "en", "nested": {"a": [1, 2]}}
    request.status = "waiting"
    requests.save_request(request)
    loaded = requests.get_request(request.request_id)
    assert loaded.steps == {"understand": {"language": "en", "nested": {"a": [1, 2]}}}
    assert loaded.status == "waiting" and loaded.updated_at >= before


def test_pending_overdue_and_next_step(requests, dataset_id):
    request = requests.new_request("new", dataset_id, "q", CHAT)
    assert request.next_step() == "understand" and request.pending() is None
    now = datetime.now(timezone.utc)
    request.clarifications.append(Exchange(step="analyze", question="Which amount?", reason="Two columns.",
                                           asked_at=now, deadline=now + timedelta(hours=1)))
    assert request.pending().question == "Which amount?"
    assert not request.pending().overdue(now)
    assert request.pending().overdue(now + timedelta(hours=2))
    request.clarifications[0].answer = "The first"
    assert request.pending() is None
    for step in STEPS:
        request.steps[step] = {}
    assert request.next_step() is None


def test_list_requests_newest_first_with_filters(requests, store, dataset_id):
    other = store.save_upload("other.csv", SALES).dataset_id
    first = requests.new_request("new", dataset_id, "one", CHAT)
    second = requests.new_request("new", other, "two", Caller(kind="terminal"))
    third = requests.new_request("new", dataset_id, "three", CHAT)
    third.status = "done"
    requests.save_request(third)
    ids = [s.request_id for s in requests.list_requests()]
    assert ids == [third.request_id, second.request_id, first.request_id]
    assert [s.request_id for s in requests.list_requests(dataset_id=dataset_id)] == [third.request_id, first.request_id]
    assert [s.request_id for s in requests.list_requests(conversation_id="chat-1", unfinished_only=True)] == [first.request_id]
    assert requests.list_requests(limit=1)[0].request_id == third.request_id


def test_unknown_and_malformed_ids(requests):
    with pytest.raises(ValueError):
        requests.get_request("rq_short")
    with pytest.raises(RequestNotFound):
        requests.get_request("rq_" + "0" * 32)
    with pytest.raises(ValueError):
        requests.get_artifact("art_short")
    with pytest.raises(ArtifactNotFound):
        requests.get_artifact("art_" + "0" * 32)


def test_artifacts_round_trip_and_lineage(requests, dataset_id):
    r1 = requests.new_request("new", dataset_id, "Total by region", CHAT)
    v1 = requests.save_artifact(artifact(requests, r1))
    r2 = requests.new_request("revise", dataset_id, "Make it blue", CHAT, parent_artifact_id=v1.artifact_id)
    v2 = requests.save_artifact(artifact(requests, r2, version=2, parent=v1.artifact_id))
    r3 = requests.new_request("revise", dataset_id, "Add a title", CHAT, parent_artifact_id=v2.artifact_id)
    v3 = requests.save_artifact(artifact(requests, r3, version=3, parent=v2.artifact_id))
    assert re.fullmatch(r"art_[0-9a-f]{32}", v1.artifact_id)
    assert requests.get_artifact(v2.artifact_id) == v2
    assert requests.artifact_for_request(r2.request_id) == v2
    assert requests.artifact_for_request(requests.new_request("new", dataset_id, "x", CHAT).request_id) is None
    by_dataset = [s.artifact_id for s in requests.list_artifacts(dataset_id=dataset_id)]
    assert by_dataset == [v3.artifact_id, v2.artifact_id, v1.artifact_id]
    for anchor in (v1, v2, v3):
        lineage = [s.artifact_id for s in requests.list_artifacts(artifact_id=anchor.artifact_id)]
        assert lineage == [v3.artifact_id, v2.artifact_id, v1.artifact_id]
    summary = requests.list_artifacts(artifact_id=v2.artifact_id)[1]
    assert summary.version == 2 and summary.parent_artifact_id == v1.artifact_id and summary.chart is None


def test_lead_artifact_bounds_the_rows(requests, dataset_id):
    from vis_agent.analyst.models import Analysis, QueryResult, ResultColumn

    request = requests.new_request("new", dataset_id, "q", CHAT)
    rows = [[f"r{i}", i] for i in range(80)]
    full = artifact(requests, request)
    full.report.analysis = Analysis(sql="SELECT 1", columns=[
        ResultColumn(name="region", meaning="Region", kind="category"),
        ResultColumn(name="total", meaning="Total", kind="measure", aggregate="sum")], summary="Eighty rows.")
    full.report.result = QueryResult(sql="SELECT 1", columns=["region", "total"], types=["VARCHAR", "BIGINT"],
                                     rows=rows, row_count=80, seconds=0)
    view = LeadArtifact.from_artifact(full)
    assert len(view.rows) == 50 and view.row_count == 80 and view.summary == "Eighty rows."
    assert view.chart is None and view.png_url is None


def test_caller_rejects_a_return_address_that_is_not_http():
    with pytest.raises(ValueError):
        Caller(kind="agent", identity="reporter", return_address="ftp://x")
    assert Caller(kind="agent", identity="reporter", return_address="https://x/cb").return_address == "https://x/cb"


def test_request_revision_round_trips(requests, dataset_id):
    request = requests.new_request("new", dataset_id, "Total by region", CHAT)
    request.revision = AnalysisRevision(problem="No series", requested_change="Add a series", preserve="The total")
    requests.save_request(request)
    assert requests.get_request(request.request_id).revision == request.revision


def test_a_stored_request_without_revision_loads_as_none(requests, dataset_id):
    request = requests.new_request("new", dataset_id, "Total by region", CHAT)
    record = request.model_dump(mode="json")
    record.pop("revision", None)
    with requests.connect() as connection:
        connection.execute("UPDATE requests SET record = ? WHERE id = ?", [json.dumps(record), request.request_id])
    assert requests.get_request(request.request_id).revision is None
