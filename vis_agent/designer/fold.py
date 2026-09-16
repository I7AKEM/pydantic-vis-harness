"""Fold measure columns of one unit into a series column and a value column, in code, never in SQL."""

from dataclasses import dataclass

from vis_agent.analyst.models import QueryResult, ResultColumn

PSEUDO_NAMES = {"ar": ("السلسلة", "القيمة"), "en": ("Series", "Value")}


class FoldError(ValueError):
    """The named columns cannot be folded; the message says why in plain words."""


@dataclass
class Folded:
    columns: list[ResultColumn]
    result: QueryResult
    series: str
    value: str


def foldable(columns: list[ResultColumn]) -> list[str]:
    """The largest set of measures or shares sharing one kind, one unit, and one aggregate, when it has two or more;
    the first on a tie. A count beside an average never folds: they are not one scale, whatever their units say."""
    groups: dict[tuple[str, str | None, str], list[str]] = {}
    for column in columns:
        if column.kind in ("measure", "share"):
            groups.setdefault((column.kind, column.unit, column.aggregate), []).append(column.name)
    best = max(groups.values(), key=len, default=[])
    return best if len(best) >= 2 else []


def _unique(name: str, taken: set[str]) -> str:
    candidate, n = name, 2
    while candidate in taken:
        candidate, n = f"{name} {n}", n + 1
    return candidate


def fold(columns: list[ResultColumn], result: QueryResult, names: list[str], language: str = "en") -> Folded:
    """One row per source row and measure, using the raw column name as its series identity."""
    by_name = {column.name: column for column in columns}
    if len(names) < 2:
        raise FoldError("fold needs two or more columns.")
    if len(set(names)) != len(names):
        raise FoldError("fold names a column twice.")
    missing = [name for name in names if name not in by_name]
    if missing:
        raise FoldError(f"fold names columns that are not in the result: {', '.join(missing)}.")
    chosen = [by_name[name] for name in names]
    wrong = [c.name for c in chosen if c.kind not in ("measure", "share")]
    if wrong:
        raise FoldError(f"fold takes measures or shares only; {', '.join(wrong)} are not.")
    if len({(c.kind, c.unit) for c in chosen}) > 1:
        described = ", ".join(f"{c.name} ({c.kind}{', ' + c.unit if c.unit else ''})" for c in chosen)
        raise FoldError(f"fold needs columns of one kind and one unit; these differ: {described}. "
                        "Measures of different units go on a dual_axes.")
    if len({c.aggregate for c in chosen}) > 1:
        described = ", ".join(f"{c.name} ({c.aggregate})" for c in chosen)
        raise FoldError(f"fold needs columns aggregated the same way; these differ: {described}.")
    series_meaning, value_meaning = PSEUDO_NAMES.get(language, PSEUDO_NAMES["en"])
    series_name = _unique(series_meaning, set(result.columns))
    value_name = _unique(value_meaning, set(result.columns) | {series_name})
    labels = [c.meaning.strip() or c.name for c in chosen]
    if len(set(labels)) != len(labels):
        labels = [c.name for c in chosen]
    first = chosen[0]
    kept = [c for c in columns if c.name not in names]
    folded_columns = [*kept,
                      ResultColumn(name=series_name, meaning=series_meaning, kind="category", aggregate="none"),
                      ResultColumn(name=value_name, meaning=", ".join(labels), kind=first.kind, unit=first.unit,
                                   aggregate=first.aggregate, denominator=first.denominator)]
    kept_index = [result.columns.index(c.name) for c in kept]
    fold_index = [result.columns.index(name) for name in names]
    rows = []
    for row in result.rows:
        base = [row[i] for i in kept_index]
        for name, index in zip(names, fold_index):
            rows.append([*base, name, row[index]])
    types = [result.types[i] for i in kept_index] + ["VARCHAR", result.types[fold_index[0]]]
    folded_result = QueryResult(sql=result.sql, columns=[c.name for c in folded_columns], types=types, rows=rows,
                                row_count=result.row_count * len(names), seconds=result.seconds)
    return Folded(folded_columns, folded_result, series_name, value_name)
