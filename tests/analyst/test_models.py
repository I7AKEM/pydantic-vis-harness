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
