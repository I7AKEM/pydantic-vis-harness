"""Small result builders, also usable from parametrized tests."""

from vis_agent.analyst.models import QueryResult, ResultColumn


def column(name, kind, source=None, aggregate="none", unit=None, denominator=None):
    return ResultColumn(name=name, meaning=name, kind=kind, source=source,
                        aggregate=aggregate, unit=unit, denominator=denominator)


def table(columns, rows, types=None):
    return QueryResult(sql="x", columns=[c.name for c in columns],
                       types=types or ["VARCHAR"] * len(columns), rows=rows,
                       row_count=len(rows), seconds=0)


def cities(n=5):
    columns = [column("city", "category", "city"),
               column("violations", "measure", aggregate="count")]
    return columns, table(columns, [[f"City{i}", (n - i) * 10] for i in range(n)])


def monthly(points=12):
    columns = [column("month", "time"), column("visits", "measure", aggregate="sum")]
    rows = [[f"{2025 + i // 12}-{i % 12 + 1:02}", 100 + 145 * i / max(points - 1, 1)]
            for i in range(points)]
    return columns, table(columns, rows)


def gender_share():
    columns = [column("gender", "category", "gender"), column("label", "category", "gender"),
               column("n", "measure", aggregate="count"),
               column("share", "share", aggregate="share", unit="%", denominator="all")]
    return columns, table(columns, [["F", "Female", 60, 60.0], ["M", "Male", 40, 40.0]])


def grouped(cities_n=5):
    columns = [column("city", "category"), column("gender", "category"),
               column("n", "measure", aggregate="sum")]
    return columns, table(columns, [[f"City{i}", g, 10 + i] for i in range(cities_n) for g in ["F", "M"]])


def scatter_points(n=40):
    columns = [column("age", "measure"), column("amount", "measure")]
    return columns, table(columns, [[i + 1, (i + 1) * 10] for i in range(n)])


def raw_amounts(n=60):
    columns = [column("amount", "measure", unit="SAR")]
    return columns, table(columns, [[i + 1] for i in range(n)])


def single_number():
    columns = [column("total", "measure", aggregate="sum")]
    return columns, table(columns, [[100]])


def two_units():
    columns = [column("month", "time"), column("visits", "measure", aggregate="sum", unit="visits"),
               column("revenue", "measure", aggregate="sum", unit="SAR")]
    return columns, table(columns, [[f"2025-{i + 1:02}", 100 + i, 1000 + i] for i in range(12)])
