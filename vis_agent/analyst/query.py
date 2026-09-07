"""One read-only SELECT on the dataset's own table: parsed, allow-listed, bounded, and timed."""

import json
import math
import threading
import time
from datetime import date
from decimal import Decimal

import duckdb

from vis_agent.analyst.models import Cell, QueryError, QueryResult
from vis_agent.profiler.measurements import preview
from vis_agent.store import DatasetStore

ROW_CAP = 1000
TIMEOUT_SECONDS = 10


class QueryRejected(ValueError):
    """The statement is not one SELECT on the dataset's own table."""


def _nodes(tree):
    if isinstance(tree, dict):
        yield tree
        for value in tree.values():
            yield from _nodes(value)
    elif isinstance(tree, list):
        for value in tree:
            yield from _nodes(value)


def validate_sql(connection, sql: str, table: str, omitted=frozenset()) -> None:
    """Raise QueryRejected unless sql is one SELECT whose tables are the dataset's table or its own CTEs."""
    try:
        statements = connection.extract_statements(sql)
    except duckdb.Error as exc:
        raise QueryRejected(f"The SQL could not be parsed: {exc}") from exc
    if len(statements) != 1:
        raise QueryRejected("Send exactly one statement.")
    if statements[0].type != duckdb.StatementType.SELECT:
        raise QueryRejected("Only SELECT statements are allowed.")
    tree = json.loads(connection.execute("SELECT json_serialize_sql(?)", [sql]).fetchone()[0])
    if tree.get("error"):
        raise QueryRejected(f"The SQL could not be parsed: {tree.get('error_message')}")
    ctes = {entry.get("key") for node in _nodes(tree) if "cte_map" in node for entry in node["cte_map"].get("map", [])}
    real = {name for (name,) in connection.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    for node in _nodes(tree):
        if omitted and node.get("class") == "COLUMN_REF":
            name = node["column_names"][-1]
            if name.casefold() in omitted:
                raise QueryRejected(f"Column {name!r} holds long text or geometry and cannot be queried; "
                                    "count rows with count(*) instead.")
        if omitted and node.get("class") == "STAR":
            excluded = {name.casefold() for name in node.get("exclude_list", [])}
            if not omitted <= excluded:
                raise QueryRejected("Name the columns you need; * would include columns that cannot be queried: "
                                    + ", ".join(sorted(omitted - excluded)))
        kind = node.get("type")
        if kind == "TABLE_FUNCTION":
            name = (node.get("function") or {}).get("function_name", "?")
            raise QueryRejected(f"Table functions such as {name} are not allowed; query the dataset table only.")
        if kind == "BASE_TABLE":
            name = node.get("table_name")
            if node.get("schema_name") or node.get("catalog_name") or (name != table and (name in real or name not in ctes)):
                raise QueryRejected(f'Only the dataset table "{table}" may be queried; found {name!r}.')


def cell(value) -> Cell:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):  # datetime is a date
        return value.isoformat()
    return preview(value)


def run_sql(store: DatasetStore, dataset_id: str, sql: str, *, omitted=frozenset(), row_cap: int = ROW_CAP,
            timeout: float = TIMEOUT_SECONDS) -> QueryResult | QueryError:
    """Validate, run with a timeout, fetch at most row_cap + 1 rows, cap cells. Errors come back for the model."""
    table = store.table_name(dataset_id)
    started = time.perf_counter()
    with store.connect() as connection:
        try:
            validate_sql(connection, sql, table, omitted=omitted)
        except QueryRejected as exc:
            return QueryError(sql=sql, error=str(exc))
        timer = threading.Timer(timeout, connection.interrupt)
        timer.start()
        try:
            relation = connection.sql(sql)
            names, types = list(relation.columns), [str(t) for t in relation.types]
            rows = relation.fetchmany(row_cap + 1)
        except duckdb.InterruptException:
            return QueryError(sql=sql, error=f"The query was stopped after {timeout} seconds.",
                              hint="Aggregate more, filter more, or avoid joins of the table with itself.")
        except duckdb.Error as exc:
            return QueryError(sql=sql, error=str(exc))
        finally:
            timer.cancel()
    if len(rows) > row_cap:
        return QueryError(sql=sql, error=f"The result has more than {row_cap} rows.",
                          hint="Aggregate, bucket time more coarsely, or take a top N with an Other row.")
    return QueryResult(sql=sql, columns=names, types=types, rows=[[cell(v) for v in row] for row in rows],
                       row_count=len(rows), seconds=time.perf_counter() - started)
