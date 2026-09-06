import asyncio
import re

import pytest
from pydantic_ai import ModelRetry, RunContext, capture_run_messages
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from starlette.applications import Starlette
from starlette.testclient import TestClient

from dataset_store import DatasetStore
from profile_models import PROFILE_VERSION, DatasetProfile
from profiler import AppDeps, compute_statistics, create_semantic_profiler, profile_csv
from uploads import add_upload_routes

SALES = (
    b"id,region,date,amount\n"
    b"001,East,2026-01-01,10\n"
    b"002,West,2026-01-02,20\n"
    b"002,West,2026-01-02,20\n"
    b"003,,2026-01-03,\n"
)


def semantic_output(names):
    return {
        "description": "A sample sales dataset.",
        "row_meaning": "A recorded sale, with possible duplicate records.",
        "columns": [
            {"name": name, "meaning": None, "role": "unknown", "unit": None,
             "confidence": "low", "evidence": "The header alone is insufficient."}
            for name in names
        ],
        "questions": ["What currency is used for amount?"],
    }


def tool_context(store):
    return RunContext(
        deps=AppDeps(store, create_semantic_profiler("test")),
        model=TestModel(),
        usage=RunUsage(),
    )


def test_statistics_and_persistence(store):
    source = store.save_upload("sales.csv", SALES)
    store.import_csv(source.dataset_id)
    profile = compute_statistics(store, source)
    assert (profile.row_count, profile.column_count, profile.duplicate_rows) == (4, 4, 1)
    columns = {column.name: column for column in profile.columns}
    assert columns["id"].physical_type == "VARCHAR"
    assert profile.sample_rows[0]["id"] == "001"
    assert columns["region"].null_percentage == 25
    assert columns["region"].common_values[0].model_dump() == {"value": "West", "count": 2}
    assert columns["date"].earliest == "2026-01-01"
    assert columns["date"].latest == "2026-01-03"
    numeric = columns["amount"].numeric
    assert numeric.mean == pytest.approx(50 / 3)
    assert numeric.standard_deviation == pytest.approx(4.71404520791)
    assert (numeric.q25, numeric.median, numeric.q75) == (15, 20, 20)
    reopened = DatasetStore(store.directory)
    assert compute_statistics(reopened, source) == profile
    other = store.save_upload("sales.csv", SALES)
    assert other.dataset_id != source.dataset_id


@pytest.mark.parametrize("content", [
    b"", b"a,b\n1\n", b"a,a\n1,2\n", b"a,\n1,2\n", b'a,b\n1,"unfinished\n', b"a\n\xff\n",
])
def test_invalid_csv_does_not_leave_files(store, content):
    with pytest.raises(ValueError):
        store.save_upload("bad.csv", content)
    assert list(store.uploads.iterdir()) == []
    with store.connect() as connection:
        assert connection.execute("SELECT count(*) FROM datasets").fetchone()[0] == 0


def test_empty_data_and_quoted_headers(store):
    source = store.save_upload("empty.csv", b'"a""b",rowid\n')
    store.import_csv(source.dataset_id)
    profile = compute_statistics(store, source)
    assert profile.row_count == 0
    assert [c.name for c in profile.columns] == ['a"b', "rowid"]
    assert profile.warnings
    with pytest.raises(ValueError):
        store.import_csv("../../.env")


def test_nonfinite_numbers_and_missing_values(store):
    source = store.save_upload("values.csv", b"value,missing\n1,\nNaN,\nInfinity,\n3,\n")
    store.import_csv(source.dataset_id)
    profile = compute_statistics(store, source)
    numeric = profile.columns[0].numeric
    assert numeric.finite_count == 2
    assert numeric.non_finite_count == 2
    assert numeric.mean == 2
    assert profile.columns[1].null_count == 4
    assert len(profile.warnings) == 2


def test_one_tool_combines_validates_and_caches(store):
    source = store.save_upload("sales.csv", SALES)
    ctx = tool_context(store)
    with ctx.deps.semantic_profiler.override(model=TestModel(custom_output_args=semantic_output(source.headers))):
        result = asyncio.run(profile_csv(ctx, source.dataset_id))
    assert result.status == "complete"
    assert result.deterministic.row_count == 4
    assert result.semantic.questions == ["What currency is used for amount?"]
    assert ctx.usage.requests > 0
    assert DatasetProfile.model_validate_json(result.model_dump_json()) == result
    assert DatasetStore(store.directory).get_profile(source.dataset_id) == result
    previous_requests = ctx.usage.requests
    assert asyncio.run(profile_csv(ctx, source.dataset_id)) == result
    assert ctx.usage.requests == previous_requests


def test_invalid_semantic_columns_save_partial_then_retry(store):
    source = store.save_upload("sales.csv", SALES)
    ctx = tool_context(store)
    with ctx.deps.semantic_profiler.override(model=TestModel(custom_output_args=semantic_output(["invented"]))):
        partial = asyncio.run(profile_csv(ctx, source.dataset_id))
    assert partial.status == "partial"
    assert partial.semantic is None
    assert partial.deterministic.row_count == 4
    assert store.get_profile(source.dataset_id) == partial
    with ctx.deps.semantic_profiler.override(model=TestModel(custom_output_args=semantic_output(source.headers))):
        complete = asyncio.run(profile_csv(ctx, source.dataset_id))
    assert complete.status == "complete"
    assert complete.deterministic == partial.deterministic


def test_unknown_id_is_a_model_retry(store):
    with pytest.raises(ModelRetry, match="not found"):
        asyncio.run(profile_csv(tool_context(store), "ds_" + "0" * 32))


def test_wkt_stays_in_storage_and_old_profiles_are_recomputed(store):
    geometry = "MULTIPOLYGON (((45 19,46 20,45 19)))"
    source = store.save_upload("map.csv", f'region,WKT\nRiyadh,"{geometry}"\n'.encode())
    ctx = tool_context(store)
    with ctx.deps.semantic_profiler.override(model=TestModel(custom_output_args=semantic_output(source.headers))):
        with capture_run_messages() as messages:
            result = asyncio.run(profile_csv(ctx, source.dataset_id))
        assert geometry not in str(messages)
        assert "MULTIPOLYGON" not in result.model_dump_json()
        assert result.deterministic.columns[1].values_omitted
        assert result.deterministic.columns[1].common_values == []
        assert result.deterministic.sample_rows == [{"region": "Riyadh"}]
        with store.connect() as connection:
            assert connection.execute(f'SELECT WKT FROM "{source.dataset_id}"').fetchone()[0] == geometry
        legacy = result.model_copy(update={
            "schema_version": "1.1",
            "deterministic": result.deterministic.model_copy(update={
                "sample_rows": [{"region": "Riyadh", "WKT": geometry}],
            }),
        })
        store.save_profile(legacy)
        refreshed = asyncio.run(profile_csv(ctx, source.dataset_id))
    assert refreshed.schema_version == PROFILE_VERSION
    assert "MULTIPOLYGON" not in refreshed.model_dump_json()


def test_any_oversized_text_column_is_excluded_from_model_inputs(store):
    large_value = "x" * 300
    source = store.save_upload("generic.csv", f"id,description\n1,{large_value}\n".encode())
    ctx = tool_context(store)
    with ctx.deps.semantic_profiler.override(model=TestModel(custom_output_args=semantic_output(source.headers))):
        with capture_run_messages() as messages:
            result = asyncio.run(profile_csv(ctx, source.dataset_id))
    column = result.deterministic.columns[1]
    assert column.maximum_value_bytes == 300
    assert column.values_omitted
    assert large_value not in str(messages)
    assert large_value not in result.model_dump_json()


def test_chat_upload_api_and_json_profile(store):
    app = Starlette()
    add_upload_routes(app, store)
    with TestClient(app) as client:
        assert client.get("/datasets/upload").status_code == 405
        uploaded = client.post("/datasets/upload", files={"file": ("sales.csv", SALES, "text/csv")})
        assert uploaded.status_code == 201
        dataset_id = uploaded.json()["dataset_id"]
        assert re.fullmatch(r"ds_[0-9a-f]{32}", dataset_id)
        assert uploaded.json()["filename"] == "sales.csv"
        assert "Upload CSV" in client.get("/datasets/chat-upload.js").text
        url = f"/datasets/{dataset_id}/profile"
        assert client.get(url).status_code == 404
        ctx = tool_context(store)
        with ctx.deps.semantic_profiler.override(model=TestModel(custom_output_args=semantic_output(["id", "region", "date", "amount"]))):
            asyncio.run(profile_csv(ctx, dataset_id))
        response = client.get(url)
        assert response.status_code == 200
        assert response.json()["deterministic"]["row_count"] == 4
        assert client.post("/datasets/upload", files={"file": ("bad.csv", b"a,b\n1\n")}).status_code == 400
        assert client.post("/datasets/upload", headers={"origin": "https://unrelated.example"}).status_code == 403
        assert client.post("/datasets/upload", headers={"content-length": str(store.max_upload_bytes + 65537)}).status_code == 413
