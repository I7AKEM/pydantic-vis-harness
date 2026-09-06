import asyncio

import pytest
from pydantic_ai import capture_run_messages
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from dataset_store import DatasetStore
from measurements import compute_statistics
from profile_models import DataBrief
from profiler import create_profiler, profile_dataset

SALES = (
    b"id,region,date,amount\n"
    b"001,East,2026-01-01,10\n"
    b"002,West,2026-01-02,20\n"
    b"002,West,2026-01-02,20\n"
    b"003,,2026-01-03,\n"
)


def semantic_output(names, roles=None):
    roles = roles or {}
    return {
        "description": "A sample sales dataset.",
        "row_meaning": "A recorded sale, with possible duplicate records.",
        "columns": [
            {"name": name, "meaning": None, "role": roles.get(name, "unknown"), "unit": None,
             "confidence": "low", "evidence": "The header alone is insufficient."}
            for name in names
        ],
        "questions": ["What currency is used for amount?"],
    }


def quiet(names, roles=None):
    return TestModel(call_tools=[], custom_output_args=semantic_output(names, roles))


def run(store, profiler, dataset_id, **kwargs):
    return asyncio.run(profile_dataset(store, profiler, dataset_id, **kwargs))


@pytest.fixture
def profiler():
    return create_profiler("test")


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
    numeric = columns["amount"].numeric
    assert numeric.mean == pytest.approx(50 / 3)
    assert (numeric.q25, numeric.median, numeric.q75) == (15, 20, 20)
    assert compute_statistics(DatasetStore(store.directory), source) == profile


@pytest.mark.parametrize("content", [
    b"", b"a,b\n1\n", b"a,a\n1,2\n", b"a,\n1,2\n", b'a,b\n1,"unfinished\n', b"a\n\xff\n",
])
def test_invalid_csv_does_not_leave_files(store, content):
    with pytest.raises(ValueError):
        store.save_upload("bad.csv", content)
    assert list(store.uploads.iterdir()) == []


def test_empty_data_and_quoted_headers(store):
    source = store.save_upload("empty.csv", b'"a""b",rowid\n')
    store.import_csv(source.dataset_id)
    profile = compute_statistics(store, source)
    assert profile.row_count == 0
    assert [c.name for c in profile.columns] == ['a"b', "rowid"]
    with pytest.raises(ValueError):
        store.import_csv("../../.env")


def test_nonfinite_numbers_and_missing_values(store):
    source = store.save_upload("values.csv", b"value,missing\n1,\nNaN,\nInfinity,\n3,\n")
    store.import_csv(source.dataset_id)
    profile = compute_statistics(store, source)
    assert (profile.columns[0].numeric.finite_count, profile.columns[0].numeric.non_finite_count) == (2, 2)
    assert profile.columns[1].null_count == 4


def test_profile_dataset_runs_the_agent_saves_and_reuses(store, profiler):
    source = store.save_upload("sales.csv", SALES)
    usage = RunUsage()
    with profiler.override(model=quiet(source.headers)):
        result = run(store, profiler, source.dataset_id, usage=usage)
    assert result.status == "complete"
    assert result.schema_version == "2.0"
    assert result.semantic.questions == ["What currency is used for amount?"]
    assert result.brief_fingerprint is None
    assert usage.requests == 1
    assert DatasetStore(store.directory).get_profile(source.dataset_id) == result
    with profiler.override(model=quiet(source.headers)):
        assert run(store, profiler, source.dataset_id, usage=usage) == result
    assert usage.requests == 1


def test_brief_reaches_the_model_and_changes_reuse(store, profiler):
    brief = DataBrief(raw_question="Sales by region", units={"amount": "USD"})
    source = store.save_upload("sales.csv", SALES, brief)
    with profiler.override(model=quiet(source.headers)):
        with capture_run_messages() as messages:
            first = run(store, profiler, source.dataset_id)
    assert first.brief_fingerprint == brief.fingerprint()
    assert "Sales by region" in str(messages)
    usage = RunUsage()
    with profiler.override(model=quiet(source.headers)):
        again = run(store, profiler, source.dataset_id, usage=usage)
    assert again == first and usage.requests == 0
    with profiler.override(model=quiet(source.headers)):
        changed = run(store, profiler, source.dataset_id, brief=DataBrief(raw_question="Other"), usage=usage)
    assert changed.brief_fingerprint != first.brief_fingerprint
    assert changed.deterministic == first.deterministic
    assert usage.requests == 1
    assert store.get_upload(source.dataset_id).brief.raw_question == "Other"


def test_failed_check_is_sent_back_once_then_recorded(store, profiler):
    source = store.save_upload("sales.csv", SALES)
    usage = RunUsage()
    with profiler.override(model=quiet(source.headers, {"region": "measure"})):
        result = run(store, profiler, source.dataset_id, usage=usage)
    assert result.status == "complete"
    assert usage.requests == 2
    failed = [c for c in result.review if not c.passed]
    assert [c.check for c in failed] == ["measure_is_numeric"]
    assert result.warnings == [failed[0].message]


def test_review_profile_is_the_only_output_tool(store, profiler):
    source = store.save_upload("sales.csv", SALES)

    def drive(messages, info):
        assert [t.name for t in info.output_tools] == ["review_profile"]
        assert info.function_tools == []
        return ModelResponse(parts=[ToolCallPart(tool_name="review_profile", args=semantic_output(source.headers))])

    usage = RunUsage()
    with profiler.override(model=FunctionModel(drive)):
        result = run(store, profiler, source.dataset_id, usage=usage)
    assert result.status == "complete"
    assert usage.requests == 1


def test_structural_retry_does_not_consume_the_check_send_back(store, profiler):
    source = store.save_upload("sales.csv", SALES)
    attempts = []

    def drive(messages, info):
        attempts.append(len(messages))
        names = ["invented"] if len(attempts) == 1 else source.headers
        args = semantic_output(names, {"region": "measure"})
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=args)])

    usage = RunUsage()
    with profiler.override(model=FunctionModel(drive)):
        result = run(store, profiler, source.dataset_id, usage=usage)
    assert result.status == "complete"
    assert len(attempts) == 3
    assert [c.check for c in result.review if not c.passed] == ["measure_is_numeric"]


def test_invalid_semantic_columns_save_partial_then_retry(store, profiler):
    source = store.save_upload("sales.csv", SALES)
    with profiler.override(model=quiet(["invented"])):
        partial = run(store, profiler, source.dataset_id)
    assert partial.status == "partial"
    assert partial.semantic is None
    assert store.get_profile(source.dataset_id) == partial
    with profiler.override(model=quiet(source.headers)):
        complete = run(store, profiler, source.dataset_id)
    assert complete.status == "complete"
    assert complete.deterministic == partial.deterministic


def test_unknown_and_malformed_ids(store, profiler):
    from dataset_store import DatasetNotFound

    with pytest.raises(DatasetNotFound):
        run(store, profiler, "ds_" + "0" * 32)
    with pytest.raises(ValueError, match="Invalid file ID"):
        run(store, profiler, "nope")


def test_wkt_stays_in_storage_and_old_profiles_are_recomputed(store, profiler):
    geometry = "MULTIPOLYGON (((45 19,46 20,45 19)))"
    source = store.save_upload("map.csv", f'region,WKT\nRiyadh,"{geometry}"\n'.encode())
    with profiler.override(model=quiet(source.headers)):
        with capture_run_messages() as messages:
            result = run(store, profiler, source.dataset_id)
        assert geometry not in str(messages)
        assert "MULTIPOLYGON" not in result.model_dump_json()
        assert result.deterministic.columns[1].values_omitted
        assert result.deterministic.sample_rows == [{"region": "Riyadh"}]
        with store.connect() as connection:
            assert connection.execute(f'SELECT WKT FROM "{source.dataset_id}"').fetchone()[0] == geometry
        legacy = result.model_copy(update={"schema_version": "1.2"})
        store.save_profile(legacy)
        refreshed = run(store, profiler, source.dataset_id)
    assert refreshed.schema_version == "2.0"


def test_any_oversized_text_column_is_excluded_from_model_inputs(store, profiler):
    large_value = "x" * 300
    source = store.save_upload("generic.csv", f"id,description\n1,{large_value}\n".encode())
    with profiler.override(model=quiet(source.headers)):
        with capture_run_messages() as messages:
            result = run(store, profiler, source.dataset_id)
    assert result.deterministic.columns[1].values_omitted
    assert large_value not in str(messages)
    assert large_value not in result.model_dump_json()


def test_concurrent_callers_share_one_profiling_run(store, profiler):
    source = store.save_upload("sales.csv", SALES)
    usage = RunUsage()

    async def both():
        return await asyncio.gather(
            profile_dataset(store, profiler, source.dataset_id, usage=usage),
            profile_dataset(store, profiler, source.dataset_id, usage=usage),
        )

    with profiler.override(model=quiet(source.headers)):
        first, second = asyncio.run(both())
    assert first == second
    assert usage.requests == 1
    assert store.get_profile(source.dataset_id) == first


def test_profiling_retries_once_after_a_timeout(store, profiler, monkeypatch):
    import profiler as profiler_module

    monkeypatch.setattr(profiler_module, "SEMANTIC_TIMEOUT_SECONDS", 0.2)
    source = store.save_upload("sales.csv", SALES)
    calls = []

    async def slow_then_ok(messages, info):
        calls.append(len(messages))
        if len(calls) == 1:
            await asyncio.sleep(1)
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=semantic_output(source.headers))])

    with profiler.override(model=FunctionModel(slow_then_ok)):
        result = run(store, profiler, source.dataset_id)
    assert result.status == "complete"
    assert len(calls) == 2
