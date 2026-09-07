# evals/analyst/make_expected.py
"""Compute expected.json for a case directory by running each case's reference SQL with the query guard.

    uv run python -m evals.analyst.make_expected            # evals/analyst/cases
    uv run python -m evals.analyst.make_expected --cases other_dir
"""

import argparse
import json
import tempfile
from pathlib import Path

from vis_agent.analyst.models import QueryResult
from vis_agent.analyst.query import run_sql
from vis_agent.store import DatasetStore, quote_identifier


def expected_tables(cases_dir: Path) -> dict:
    specs = json.loads((cases_dir / "cases.json").read_text(encoding="utf-8"))
    tables = {}
    with tempfile.TemporaryDirectory() as tmp:
        store = DatasetStore(Path(tmp))
        for spec in specs:
            if spec["expect"] != "table":
                continue
            path = cases_dir / spec["csv"]
            source = store.save_upload(path.name, path.read_bytes())
            store.import_csv(source.dataset_id)
            sql = spec["reference_sql"].replace("dataset", quote_identifier(source.dataset_id))
            result = run_sql(store, source.dataset_id, sql)
            if not isinstance(result, QueryResult):
                raise SystemExit(f"{spec['name']}: {result.error}")
            tables[spec["name"]] = {"columns": result.columns, "rows": result.rows}
    return tables


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default="cases")
    args = parser.parse_args()
    cases_dir = Path(__file__).with_name(args.cases)
    tables = expected_tables(cases_dir)
    (cases_dir / "expected.json").write_text(json.dumps(tables, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(tables)} expected tables to {cases_dir / 'expected.json'}")


if __name__ == "__main__":
    main()
