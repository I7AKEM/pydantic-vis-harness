import pytest

from vis_agent.analyst.models import QueryError, QueryResult
from vis_agent.analyst.query import QueryRejected, run_sql, validate_sql

SALES = b"region,amount,day\nEast,10,2026-01-01\nWest,20,2026-01-02\nWest,5,2026-01-03\n"


@pytest.fixture
def dataset(store):
    source = store.save_upload("sales.csv", SALES)
    store.import_csv(source.dataset_id)
    return source.dataset_id


def test_only_one_select_on_the_dataset_table_passes(store, dataset):
    with store.connect() as connection:
        validate_sql(connection, f'SELECT region, sum(amount) FROM "{dataset}" GROUP BY 1', dataset)
        validate_sql(connection, f'WITH t AS (SELECT * FROM "{dataset}") SELECT * FROM t', dataset)
        validate_sql(connection, f'WITH t AS (SELECT * FROM "{dataset}") SELECT * FROM t JOIN "{dataset}" d USING (region)', dataset)
        validate_sql(connection, "SELECT 1", dataset)
        for sql, reason in [
            (f'DELETE FROM "{dataset}"', "SELECT"),
            (f'SELECT 1; SELECT * FROM "{dataset}"', "one statement"),
            ("SELECT * FROM datasets", "dataset table"),
            ("WITH datasets AS (SELECT * FROM datasets) SELECT * FROM datasets", "dataset table"),
            ("SELECT * FROM information_schema.tables", "dataset table"),
            ("SELECT * FROM 'sales.csv'", "dataset table"),
            ("SELECT * FROM read_csv('sales.csv')", "Table functions"),
            ("SELECT * FROM read_text('/etc/hosts')", "Table functions"),
            ("SELECT * FROM range(10)", "Table functions"),
            ("SELEC 1", "parsed"),
        ]:
            with pytest.raises(QueryRejected, match=reason):
                validate_sql(connection, sql, dataset)


def test_omitted_columns_cannot_be_queried(store):
    source = store.save_upload("places.csv", b'region,WKT\nRiyadh,"MULTIPOLYGON (((45 19,46 20,45 19)))"\nJeddah,"POINT (39 21)"\n')
    ds = source.dataset_id
    store.import_csv(ds)
    for sql in (f'SELECT WKT FROM "{ds}"', f'SELECT d.wkt FROM "{ds}" d'):
        result = run_sql(store, ds, sql, omitted={"wkt"})
        assert isinstance(result, QueryError) and "cannot be queried" in result.error
    result = run_sql(store, ds, f'SELECT * FROM "{ds}"', omitted={"wkt"})
    assert isinstance(result, QueryError) and "*" in result.error
    result = run_sql(store, ds, f'SELECT * EXCLUDE (WKT) FROM "{ds}"', omitted={"wkt"})
    assert isinstance(result, QueryResult) and result.columns == ["region"]
    result = run_sql(store, ds, f'SELECT region, count(*) AS n FROM "{ds}" GROUP BY 1', omitted={"wkt"})
    assert isinstance(result, QueryResult)


def test_run_sql_returns_a_bounded_table(store, dataset):
    result = run_sql(store, dataset, f'SELECT region, sum(amount) AS total FROM "{dataset}" GROUP BY 1 ORDER BY 2 DESC')
    assert isinstance(result, QueryResult)
    assert result.columns == ["region", "total"]
    assert result.types == ["VARCHAR", "HUGEINT"] or result.types[0] == "VARCHAR"
    assert result.rows == [["West", 25], ["East", 10]]
    assert result.row_count == 2
    assert result.seconds >= 0
    dated = run_sql(store, dataset, f'SELECT day, amount * 1.5 AS scaled FROM "{dataset}" ORDER BY day')
    assert dated.rows[0] == ["2026-01-01", 15.0]


def test_run_sql_reports_rejections_errors_caps_and_timeouts(store, dataset):
    rejected = run_sql(store, dataset, f'DELETE FROM "{dataset}"')
    assert isinstance(rejected, QueryError) and "SELECT" in rejected.error
    failed = run_sql(store, dataset, f'SELECT nope FROM "{dataset}"')
    assert isinstance(failed, QueryError) and "nope" in failed.error
    capped = run_sql(store, dataset, f'SELECT * FROM "{dataset}"', row_cap=2)
    assert isinstance(capped, QueryError) and "2 rows" in capped.error and capped.hint
    slow = run_sql(store, dataset, f'SELECT count(*) FROM "{dataset}" a, "{dataset}" b, "{dataset}" c, '
                                   f'"{dataset}" d, "{dataset}" e, "{dataset}" f, "{dataset}" g, "{dataset}" h, '
                                   f'"{dataset}" i, "{dataset}" j, "{dataset}" k, "{dataset}" l, "{dataset}" m, '
                                   f'"{dataset}" n, "{dataset}" o, "{dataset}" p, "{dataset}" q, "{dataset}" r, '
                                   f'"{dataset}" s, "{dataset}" t, "{dataset}" u, "{dataset}" v, "{dataset}" w, '
                                   f'"{dataset}" x, "{dataset}" y, "{dataset}" z', timeout=0.2)
    assert isinstance(slow, QueryError) and "0.2 seconds" in slow.error


def test_run_sql_caps_cells(store):
    source = store.save_upload("long.csv", b"note\n" + b"x" * 300 + b"\n")
    store.import_csv(source.dataset_id)
    result = run_sql(store, source.dataset_id, f'SELECT note FROM "{source.dataset_id}"')
    assert len(result.rows[0][0]) == 121 and result.rows[0][0].endswith("…")
