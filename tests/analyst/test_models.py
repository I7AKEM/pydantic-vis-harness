import pytest
from pydantic import ValidationError

from vis_agent.analyst.models import Analysis, QueryResult, ResultColumn


def test_result_column_rules():
    ResultColumn(name="Region", meaning="The region", kind="category", source="region")
    ResultColumn(name="Total", meaning="Sum of amount", kind="measure", unit="SAR", source="amount", aggregate="sum")
    ResultColumn(name="Share", meaning="Share of all sales", kind="share", source="amount", aggregate="share",
                 denominator="the sum of amount over every region")
    with pytest.raises(ValidationError, match="unit"):
        ResultColumn(name="Region", meaning="The region", kind="category", unit="SAR")
    share = ResultColumn(name="Share", meaning="Share", kind="share", aggregate="share")
    assert share.denominator == "not stated"
    with pytest.raises(ValidationError):
        ResultColumn(name="X", meaning="X", kind="weight")


def test_query_result_keeps_cells_and_analysis_keeps_query():
    result = QueryResult(sql="SELECT 1", columns=["a"], types=["BIGINT"], rows=[[1], [None]], row_count=2, seconds=0.01)
    assert result.rows[1] == [None]
    analysis = Analysis(sql="SELECT 1", columns=[ResultColumn(name="a", meaning="one", kind="measure")],
                        summary="One row.", assumptions=[])
    assert analysis.columns[0].aggregate == "none"


@pytest.mark.parametrize("unit", ["null", "None", " n/a ", "", "-"])
def test_placeholder_units_become_null(unit):
    from vis_agent.analyst.models import ResultColumn

    column = ResultColumn(name="Graduates", meaning="Graduates", kind="measure", unit=unit)
    assert column.unit is None


@pytest.mark.parametrize("source", ["null", "None", "", "-"])
def test_placeholder_sources_become_null(source):
    column = ResultColumn(name="share_under_15", meaning="Share of people under 15", kind="share", source=source,
                          denominator="null")
    assert column.source is None and column.denominator == "not stated"


def test_share_partition_is_optional_and_preserves_explicit_empty_groups():
    old = {"name": "Share", "meaning": "Share", "kind": "share"}
    assert ResultColumn.model_validate(old).partition_by is None
    for groups in ([], ["year", "region"]):
        column = ResultColumn(**old, partition_by=groups)
        assert ResultColumn.model_validate_json(column.model_dump_json()).partition_by == groups


@pytest.mark.parametrize("changes", [
    {"partition_by": ["year", "year"]},
    {"partition_by": [" "]},
    {"partition_by": ["Share"]},
])
def test_invalid_share_partition_metadata_is_rejected(changes):
    with pytest.raises(ValidationError, match="partition_by"):
        ResultColumn.model_validate({"name": "Share", "meaning": "Share", "kind": "share", **changes})


@pytest.mark.parametrize("kind", ["measure", "category", "time", "ordinal", "geography", "identifier"])
@pytest.mark.parametrize("annotation", [[], ["year"], ["year", "region"], ["None"], ["total"], [" "], ["year", "year"]])
def test_inapplicable_partition_is_normalized_without_a_query_retry(kind, annotation):
    column = ResultColumn(name="total", meaning="Total", kind=kind, partition_by=annotation)
    assert column.partition_by is None


def test_ignoring_nonshare_partition_does_not_change_query_or_other_metadata():
    raw_column = {"name": "total", "meaning": "Total revenue", "kind": "measure", "source": "revenue",
                  "aggregate": "sum", "unit": "SAR", "partition_by": ["year"]}
    sql = 'SELECT year, sum(revenue) AS total FROM "dataset" GROUP BY year'
    analysis = Analysis(sql=sql, columns=[ResultColumn.model_validate(raw_column)], summary="Revenue by year.")
    assert analysis.sql == sql
    assert analysis.columns[0].model_dump() == {
        **raw_column, "partition_by": None, "denominator": None,
    }
    assert raw_column["partition_by"] == ["year"]


def test_literal_null_partition_is_missing_metadata():
    assert ResultColumn.model_validate({"name": "rate", "meaning": "Rate", "kind": "share",
                                        "partition_by": "null"}).partition_by is None
