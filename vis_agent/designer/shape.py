"""Facts about the analyst's bounded result, computed without a model."""

from dataclasses import dataclass, field, replace

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


@dataclass
class ResultShape:
    rows: int
    columns: list[ColumnShape]
    labels: list[ColumnShape]
    measures: list[ColumnShape]
    times: list[ColumnShape]
    identifiers: list[ColumnShape]
    # C9 needs membership, which cannot be recovered from a distinct count.
    _label_values: dict[str, set[str]] = field(default_factory=dict, init=False, repr=False)

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
    for column in columns:
        index = result.columns.index(column.name)
        cells = [row[index] for row in result.rows]
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
    return shape
