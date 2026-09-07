# tests/analyst/test_eval.py
import json

from evals.analyst.run import load_cases, tables_match


def test_tables_match_ignores_order_names_rounding_and_extra_columns():
    expected = {"columns": ["region", "total"], "rows": [["East", 40], ["West", 65.0004]]}
    assert tables_match(expected, {"columns": ["المنطقة", "المجموع"], "rows": [["West", 65], ["East", 40]]}) == 1.0
    assert tables_match(expected, {"columns": ["a", "b"], "rows": [["West", 66], ["East", 40]]}) == 0.0
    assert tables_match(expected, {"columns": ["a"], "rows": [["West"], ["East"]]}) == 0.0
    assert tables_match(expected, {"columns": ["a", "b", "c"], "rows": [["West", 65, 1], ["East", 40, 2]]}) == 1.0
    assert tables_match(expected, {"columns": ["b", "a"], "rows": [[65, "West"], [40, "East"]]}) == 1.0
    assert tables_match(expected, {"columns": ["a", "b"], "rows": [["West", 40], ["East", 65]]}) == 0.0
    assert tables_match(expected, {"columns": ["a", "b"], "rows": [["West", 65]]}) == 0.0
    months = {"columns": ["month", "n"], "rows": [["2024-01-01", 5], ["2024-02-01T00:00:00", 6]]}
    assert tables_match(months, {"columns": ["m", "n"], "rows": [["2024-01", 5], ["2024-02", 6]]}) == 1.0
    years = {"columns": ["year", "n"], "rows": [[2020, 5], [2021, 6]]}
    assert tables_match(years, {"columns": ["y", "n"], "rows": [["2020-01-01T00:00:00+03:00", 5], ["2021-01-01", 6]]}) == 1.0
    shares = {"columns": ["type", "share"], "rows": [["a", 22.6], ["b", 77.4]]}
    assert tables_match(shares, {"columns": ["t", "s"], "rows": [["a", 0.22600000000000001], ["b", 0.774]]}) == 1.0
    assert tables_match(shares, {"columns": ["t", "s"], "rows": [["a", 0.3], ["b", 0.7]]}) == 0.0


def test_load_cases_reads_the_format(tmp_path):
    (tmp_path / "data.csv").write_bytes(b"region,amount\nEast,1\n")
    (tmp_path / "cases.json").write_text(json.dumps([{"name": "one", "csv": "data.csv", "question": "Total?", "brief": None,
                                                     "reference_sql": "SELECT sum(amount) AS total FROM dataset", "expect": "table"}]))
    (tmp_path / "expected.json").write_text(json.dumps({"one": {"columns": ["total"], "rows": [[1]]}}))
    cases = load_cases(tmp_path)
    assert cases[0].name == "one" and cases[0].inputs["question"] == "Total?"
    assert cases[0].expected_output == {"expect": "table", "columns": ["total"], "rows": [[1]]}
