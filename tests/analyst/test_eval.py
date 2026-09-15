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


def test_indicator_sql_golds_do_not_allow_100x_scale_changes():
    from pathlib import Path
    from evals.analyst.make_expected import expected_tables
    directory = Path(__file__).resolve().parents[2] / 'evals/analyst/indicator'
    assert expected_tables(directory) == json.loads((directory / 'expected.json').read_text())
    cases = load_cases(directory)
    assert len(cases) >= 8 and all(c.expected_output['strict_scale'] for c in cases)
    rate = next(c for c in cases if c.name == 'indicator_weighted_rate')
    assert rate.expected_output['rows'] == [[20.0]]
    assert tables_match(rate.expected_output, {'columns': ['rate'], 'rows': [[0.2]]}) == 0
    assert tables_match(rate.expected_output, {'columns': ['rate'], 'rows': [[20]]}) == 1


def test_evidence_and_mismatches_preserve_error_checks_even_when_values_match(tmp_path, capsys):
    import asyncio
    from pathlib import Path
    from pydantic_evals import Case, Dataset
    from vis_agent.analyst.models import AnalysisReport
    from vis_agent.profiler.models import ProfileCheck
    from evals.analyst.run import TableMatches, ChecksClean, print_mismatch, write_evidence
    source = Path(__file__).resolve().parents[2] / 'evals/designer/agent/indicator/reports/dev_change.json'
    output = AnalysisReport.model_validate_json(source.read_text())
    output.checks = [ProfileCheck(column=None, check='summary_numbers_exist', severity='error', passed=False,
                                  message='The summary mentions an unsupported number.')]
    case = Case(name='change', inputs={'question': output.question, 'csv': 'fixture.csv'},
                expected_output={'expect': 'table', 'columns': ['change'], 'rows': [[-148.75]], 'strict_scale': True})
    report = asyncio.run(Dataset(name='evidence', cases=[case], evaluators=[TableMatches(), ChecksClean()]).evaluate(lambda inputs: output))
    (tmp_path / 'cases.json').write_text('[]')
    path = tmp_path / 'evidence/run.json'
    write_evidence(path, report, tmp_path, {'analyst': 'test', 'profiler': 'test'})
    saved = json.loads(path.read_text())
    result = saved['cases'][0]
    assert result['scores']['TableMatches'] == 1
    assert result['assertions']['ChecksClean'] is False
    assert result['output']['checks'][0]['message'] == output.checks[0].message
    assert saved['provenance']['models']['analyst'] == 'test'
    print_mismatch(case, output)
    printed = capsys.readouterr().out
    assert 'summary_numbers_exist' in printed and 'sql:' in printed
    assert 'expected [[' not in printed


def test_analyst_help_advertises_portable_evidence():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-m', 'evals.analyst.run', '--help'], capture_output=True, text=True)
    assert result.returncode == 0 and '--out' in result.stdout
