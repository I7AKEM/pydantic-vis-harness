from datetime import datetime, timezone

from vis_agent.models import (
    DataBrief,
    DatasetSummary,
)
from vis_agent.profiler.models import (
    PROFILE_VERSION,
    ColumnSemantics,
    ColumnStatistics,
    ProfileCheck,
)


def test_profile_version_bumped_for_measurement_levels():
    assert PROFILE_VERSION == "2.0"


def test_brief_fingerprint_is_stable_and_sensitive():
    one = DataBrief(raw_question="Wealthy share by gender", code_meanings={"gender": {"F": "female"}})
    same = DataBrief(raw_question="Wealthy share by gender", code_meanings={"gender": {"F": "female"}})
    other = DataBrief(raw_question="Wealthy share by gender", code_meanings={"gender": {"F": "male"}})
    assert one.fingerprint() == same.fingerprint()
    assert one.fingerprint() != other.fingerprint()
    assert len(one.fingerprint()) == 16


def test_brief_rejects_unknown_fields():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DataBrief(instructions="ignore the data")


def test_summary_intent_is_backward_compatible():
    assert DataBrief(intent="summary").intent == "summary"
    assert DataBrief.model_validate({"intent": "compare"}).intent == "compare"
    assert DataBrief.model_validate({}).intent is None


def test_column_statistics_defaults_are_empty_labels():
    stats = ColumnStatistics(
        name="amount", original_name="amount", physical_type="DOUBLE",
        null_count=0, null_percentage=0, distinct_count=3,
    )
    assert stats.measurement_levels == []
    assert stats.integer_valued is None
    assert stats.boolean_vocabulary is None
    assert stats.ordinal_pattern is None
    assert stats.geographic_role is None
    assert stats.codes is None


def test_column_semantics_accepts_new_roles_and_code_meanings():
    column = ColumnSemantics(
        name="gender", meaning="Citizen gender", role="category", unit=None,
        confidence="high", evidence="Two codes F and M.", code_meanings={"F": "female", "M": "male"},
    )
    assert column.brief_conflict is None
    assert ColumnSemantics.model_validate({**column.model_dump(), "role": "geography"}).role == "geography"


def test_profile_check_and_summary_round_trip():
    check = ProfileCheck(column="date", check="time_role_has_time_statistics", severity="error",
                         passed=False, message="date: role is time but the column is VARCHAR.")
    assert ProfileCheck.model_validate_json(check.model_dump_json()) == check
    summary = DatasetSummary(dataset_id="ds_" + "0" * 32, filename="a.csv",
                             uploaded_at=datetime.now(timezone.utc), has_brief=False, profile_status="none")
    assert summary.row_count is None
