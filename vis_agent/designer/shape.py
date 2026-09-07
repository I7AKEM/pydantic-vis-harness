"""Facts about the analyst's bounded result, computed without a model."""

import json
from dataclasses import dataclass, field, replace
from itertools import combinations

import duckdb

from vis_agent.analyst.models import Aggregate, ColumnKind, QueryResult, ResultColumn


@dataclass
class ColumnShape:
    name: str
    kind: ColumnKind
    unit: str | None
    aggregate: Aggregate
    source: str | None
    distinct: int
    longest_label: int
    minimum: int | float | None
    maximum: int | float | None
    has_negative: bool
    is_numeric: bool
    nulls: int
    sums_to_whole: bool | None = None


@dataclass
class ResultShape:
    rows: int
    columns: list[ColumnShape]
    labels: list[ColumnShape]
    measures: list[ColumnShape]
    times: list[ColumnShape]
    identifiers: list[ColumnShape]
    aliases: set[frozenset[str]] = field(default_factory=set)
    # C9 needs membership, which cannot be recovered from a distinct count.
    _label_values: dict[str, set[str]] = field(default_factory=dict, init=False, repr=False)

    def is_alias(self, a: str, b: str) -> bool:
        return frozenset((a, b)) in self.aliases

    def limited(self, column_name: str, count: int) -> "ResultShape":
        """Copy displayed cardinality, retaining every raw value statistic."""
        def update(columns):
            return [replace(c, distinct=min(c.distinct, count + 1))
                    if c.name == column_name else c for c in columns]

        limited = replace(self, **{name: update(getattr(self, name))
                                  for name in ("columns", "labels", "measures", "times", "identifiers")})
        limited._label_values = self._label_values
        return limited

    def column(self, name: str) -> ColumnShape:
        for column in self.columns:
            if column.name == name:
                return column
        raise KeyError(name)


def describe(columns: list[ResultColumn], result: QueryResult) -> ResultShape:
    summaries = []
    label_values = {}
    cells_by_name = {}
    for column in columns:
        index = result.columns.index(column.name)
        cells = [row[index] for row in result.rows]
        cells_by_name[column.name] = cells
        present = [cell for cell in cells if cell is not None]
        numbers = [cell for cell in present if isinstance(cell, (int, float)) and not isinstance(cell, bool)]
        summaries.append(ColumnShape(
            name=column.name, kind=column.kind, unit=column.unit,
            aggregate=column.aggregate, source=column.source,
            distinct=len(set(present)), longest_label=max((len(str(v)) for v in present), default=0),
            minimum=min(numbers, default=None), maximum=max(numbers, default=None),
            has_negative=any(v < 0 for v in numbers), is_numeric=len(numbers) == len(present),
            nulls=len(cells) - len(present),
        ))
        if column.kind in ("category", "ordinal", "geography", "time"):
            label_values[column.name] = {str(v) for v in present}
    shape = ResultShape(
        rows=result.row_count, columns=summaries,
        labels=[c for c in summaries if c.kind in ("category", "ordinal", "geography")],
        measures=[c for c in summaries if c.kind in ("measure", "share")],
        times=[c for c in summaries if c.kind == "time"],
        identifiers=[c for c in summaries if c.kind == "identifier"],
    )
    shape._label_values = label_values
    # Measure new facts in DuckDB; physical result types may be fixture placeholders.
    # JSON preserves numeric codes versus text codes instead of coercing mixed lists.
    alias_cells = {c.name: [json.dumps(v) if v is not None else None for v in cells_by_name[c.name]]
                   for c in shape.labels}
    with duckdb.connect(config={"threads": 1}) as connection:
        for a, b in combinations(shape.labels, 2):
            pairs, distinct_a, distinct_b = connection.execute(
                "SELECT count(DISTINCT (a, b)), count(DISTINCT a), count(DISTINCT b) "
                "FROM (SELECT unnest(?) a, unnest(?) b)",
                [alias_cells[a.name], alias_cells[b.name]],
            ).fetchone()
            if pairs > 0 and pairs == distinct_a == distinct_b:
                shape.aliases.add(frozenset((a.name, b.name)))
        for column in shape.measures:
            if column.kind != "share":
                continue
            column.sums_to_whole = False
            if column.is_numeric:
                total, = connection.execute(
                    "SELECT sum(value) FROM unnest(?::DOUBLE[]) AS cells(value)",
                    [cells_by_name[column.name]],
                ).fetchone()
                column.sums_to_whole = total is not None and (99 <= total <= 101 or 0.99 <= total <= 1.01)
    return shape
