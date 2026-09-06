"""Every statistic and every measurement label comes from a DuckDB query. Python assigns labels."""

import math
import re

from dataset_store import DatasetStore, quote_identifier
from profile_models import (
    ColumnStatistics,
    DeterministicProfile,
    NumericStatistics,
    UploadedDataset,
    ValueCount,
)

SAMPLE_ROWS = 5
VALUE_CHARACTERS = 120
MAX_MODEL_VALUE_BYTES = 256
MAX_DETAILED_COLUMNS = 40  # columns past this get counts and types only, so the prompt stays bounded
MAX_ORDINAL_DISTINCT = 50
MAX_CODE_DISTINCT = 12
MAX_CODE_LENGTH = 3
INTEGER_TYPES = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
                 "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT")
NUMERIC_TYPES = INTEGER_TYPES + ("FLOAT", "DOUBLE", "DECIMAL")
TIME_TYPES = ("DATE", "TIMESTAMP", "TIME")

GEOMETRY_NAME = re.compile(r"(^|[_\s])(wkt|geom|geometry|the_geom|shape)($|[_\s])", re.IGNORECASE)
LATITUDE_NAME = re.compile(r"(^|[_\s])(lat|latitude)($|[_\s])", re.IGNORECASE)
LONGITUDE_NAME = re.compile(r"(^|[_\s])(lon|lng|long|longitude)($|[_\s])", re.IGNORECASE)
PLACE_TOKENS = ("country", "region", "city", "cities", "state", "province", "district", "governorate", "county",
                "municipality", "location", "port", "airport", "station", "town", "village", "neighborhood", "zone",
                "address", "منطقة", "مدينة", "محافظة", "بلدية", "حي", "مطار", "منفذ", "ميناء", "قرية", "دولة", "موقع")
MEASURE_TOKENS = ("count", "total", "sum", "avg", "mean", "percentage", "percent", "rate", "ratio", "size", "number",
                  "num", "value", "amount", "share", "category", "mode", "type")
PLACE_NAME = re.compile(r"(^|[_\s])(ال)?(" + "|".join(PLACE_TOKENS) + r")($|[_\s])", re.IGNORECASE)
MEASURE_NAME = re.compile(r"(^|[_\s])(" + "|".join(MEASURE_TOKENS) + r")($|[_\s])", re.IGNORECASE)
# RE2 syntax, evaluated inside DuckDB. Values never leave the database for these checks.
WKT_SQL_PATTERN = r"^\s*(SRID=\d+;)?(POINT|LINESTRING|POLYGON|MULTIPOINT|MULTILINESTRING|MULTIPOLYGON|GEOMETRYCOLLECTION)\b"
ORDINAL_SQL_PATTERN = r"^\D*\d+\D*$"
DIGITS_SQL_PATTERN = r"\d+"
BOOLEAN_PAIRS = [
    {"true", "false"}, {"yes", "no"}, {"y", "n"}, {"t", "f"}, {"on", "off"}, {"نعم", "لا"},
]


def preview(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= VALUE_CHARACTERS else text[:VALUE_CHARACTERS] + "…"


def finite_number(value: object) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def compute_statistics(store: DatasetStore, source: UploadedDataset) -> DeterministicProfile:
    table = quote_identifier(store.table_name(source.dataset_id))
    columns = []
    warnings = []
    with store.connect() as connection:
        schema = connection.execute(f"DESCRIBE {table}").fetchall()
        row_count = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        unique_rows = connection.execute(f"SELECT count(*) FROM (SELECT DISTINCT * FROM {table})").fetchone()[0]
        for index, (name, physical_type, *_rest) in enumerate(schema):
            column = quote_identifier(name)
            null_count, distinct_count, maximum_value_bytes = connection.execute(
                f"SELECT count(*) - count({column}), count(DISTINCT {column}), "
                f"coalesce(max(octet_length(encode(CAST({column} AS VARCHAR)))), 0) FROM {table}"
            ).fetchone()
            is_text = physical_type == "VARCHAR"
            wkt_count = 0
            if is_text:
                wkt_count = connection.execute(
                    f"SELECT count(*) FILTER (WHERE regexp_matches({column}, ?, 'i')) FROM {table}",
                    [WKT_SQL_PATTERN],
                ).fetchone()[0]
            geometry_name = bool(GEOMETRY_NAME.search(name))
            stats = ColumnStatistics(
                name=name,
                original_name=source.headers[index],
                physical_type=physical_type,
                null_count=null_count,
                null_percentage=100 * null_count / row_count if row_count else 0,
                distinct_count=distinct_count,
                maximum_value_bytes=maximum_value_bytes,
                values_omitted=maximum_value_bytes > MAX_MODEL_VALUE_BYTES or geometry_name or wkt_count > 0
                or index >= MAX_DETAILED_COLUMNS,
            )
            if row_count and null_count == row_count:
                warnings.append(f"{name}: all values are null.")
            elif distinct_count == 1:
                warnings.append(f"{name}: only one distinct non-null value.")

            # Decide from the entire column, before retrieving any values for a model.
            if stats.values_omitted:
                if physical_type.startswith(TIME_TYPES):
                    stats.measurement_levels = ["time"]
                elif physical_type.startswith(NUMERIC_TYPES):
                    stats.measurement_levels = ["interval"]
                else:
                    stats.measurement_levels = ["nominal"]
                    if geometry_name or wkt_count > 0:
                        stats.geographic_role = "wkt"
                        stats.measurement_levels.append("geographic")
                columns.append(stats)
                continue

            if physical_type.startswith(NUMERIC_TYPES):
                _numeric_labels(connection, table, column, name, stats, row_count, null_count, warnings)
            elif physical_type.startswith(TIME_TYPES):
                stats.measurement_levels = ["time"]
            elif physical_type == "BOOLEAN":
                # DuckDB normalizes yes/no to BOOLEAN at import.
                stats.measurement_levels = ["nominal"]
                stats.boolean_vocabulary = ["false", "true"]
            else:
                stats.measurement_levels = ["nominal"]
                if geometry_name or wkt_count > 0:
                    stats.geographic_role = "wkt"
                elif PLACE_NAME.search(name) and not MEASURE_NAME.search(name):
                    stats.geographic_role = "place_name"
                if stats.geographic_role is not None:
                    stats.measurement_levels.append("geographic")

            if physical_type.startswith(TIME_TYPES):
                earliest, latest = connection.execute(
                    f"SELECT min({column}), max({column}) FROM {table}"
                ).fetchone()
                stats.earliest, stats.latest = preview(earliest), preview(latest)
            elif not physical_type.startswith(NUMERIC_TYPES):
                common = connection.execute(
                    f"SELECT {column}, count(*) AS frequency FROM {table} "
                    f"WHERE {column} IS NOT NULL GROUP BY {column} "
                    f"ORDER BY frequency DESC, {column} ASC LIMIT 5"
                ).fetchall()
                stats.common_values = [ValueCount(value=preview(value), count=count) for value, count in common]
                if is_text:
                    _text_labels(connection, table, column, stats, distinct_count, row_count - null_count)
            columns.append(stats)

        # Oversized columns stay in DuckDB; neither agent receives their values.
        sample_names = [c.name for c in columns if not c.values_omitted]
        sample = []
        if sample_names:
            selection = ", ".join(map(quote_identifier, sample_names))
            rows = connection.execute(f"SELECT {selection} FROM {table} LIMIT {SAMPLE_ROWS}").fetchall()
            sample = [dict(zip(sample_names, map(preview, row))) for row in rows]
    if len(columns) > MAX_DETAILED_COLUMNS:
        warnings.append(
            f"Only the first {MAX_DETAILED_COLUMNS} columns include statistics, samples, and common values; "
            f"{len(columns) - MAX_DETAILED_COLUMNS} more columns include metadata and counts only."
        )
    if row_count == 0:
        warnings.append("The CSV has a header but no data rows.")
    return DeterministicProfile(
        row_count=row_count,
        column_count=len(columns),
        duplicate_rows=row_count - unique_rows,
        columns=columns,
        sample_rows=sample,
        sample_description=(
            f"Statistics cover every imported row. Sample: first {SAMPLE_ROWS} rows in import order; "
            f"sample and common-value text is capped at {VALUE_CHARACTERS} characters. "
            f"Columns containing any value over {MAX_MODEL_VALUE_BYTES} UTF-8 bytes, any WKT value, "
            "or named like geometry are excluded entirely from samples and common values; only metadata "
            f"and counts are included, as are all columns after the first {MAX_DETAILED_COLUMNS}. "
            "Measurement levels are assigned from whole-column queries. "
            "Numeric aggregates use finite double-precision values and population standard deviation. "
            "CSV settings: UTF-8, comma delimiter, header row, full-file type inference, empty fields as null."
        ),
        warnings=warnings,
    )


def _numeric_labels(connection, table, column, name, stats, row_count, null_count, warnings) -> None:
    finite_count, *metrics = connection.execute(
        f"SELECT count(*), min(v), max(v), avg(v), stddev_pop(v), "
        "quantile_cont(v, 0.25), quantile_cont(v, 0.5), quantile_cont(v, 0.75) "
        f"FROM (SELECT CAST({column} AS DOUBLE) AS v FROM {table}) WHERE isfinite(v)"
    ).fetchone()
    stats.numeric = NumericStatistics(
        finite_count=finite_count,
        non_finite_count=row_count - null_count - finite_count,
        **dict(zip(
            ["minimum", "maximum", "mean", "standard_deviation", "q25", "median", "q75"],
            map(finite_number, metrics),
        )),
    )
    if stats.numeric.non_finite_count:
        warnings.append(f"{name}: numeric statistics exclude non-finite values.")
    if stats.physical_type.startswith(INTEGER_TYPES):
        stats.integer_valued = True
    elif finite_count:
        stats.integer_valued = bool(connection.execute(
            f"SELECT bool_and(v = floor(v)) FROM (SELECT CAST({column} AS DOUBLE) AS v FROM {table}) WHERE isfinite(v)"
        ).fetchone()[0])
    stats.measurement_levels = ["interval", "discrete" if stats.integer_valued else "continuous"]
    low, high = stats.numeric.minimum, stats.numeric.maximum
    if low is not None and high is not None:
        if LATITUDE_NAME.search(name) and -90 <= low and high <= 90:
            stats.geographic_role = "latitude"
        elif LONGITUDE_NAME.search(name) and -180 <= low and high <= 180:
            stats.geographic_role = "longitude"
    if stats.geographic_role is not None:
        stats.measurement_levels.append("geographic")


def _text_labels(connection, table, column, stats, distinct_count, non_null) -> None:
    if distinct_count == 2:
        (values,) = connection.execute(
            f"SELECT list(DISTINCT lower(trim({column}))) FROM {table} WHERE {column} IS NOT NULL"
        ).fetchone()
        if set(values) in BOOLEAN_PAIRS:
            stats.boolean_vocabulary = sorted(values)
    if 2 <= distinct_count <= MAX_ORDINAL_DISTINCT and distinct_count < non_null:
        non_matching, templates = connection.execute(
            f"SELECT count(*) FILTER (WHERE NOT regexp_matches({column}, ?)), "
            f"count(DISTINCT regexp_replace({column}, ?, '#', 'g')) FROM {table} WHERE {column} IS NOT NULL",
            [ORDINAL_SQL_PATTERN, DIGITS_SQL_PATTERN],
        ).fetchone()
        if non_matching == 0 and templates == 1:
            stats.ordinal_pattern = connection.execute(
                f"SELECT regexp_replace(min({column}), ?, '#', 'g') FROM {table}", [DIGITS_SQL_PATTERN]
            ).fetchone()[0]
            stats.measurement_levels.append("ordinal")
    if 1 <= distinct_count <= MAX_CODE_DISTINCT and distinct_count < non_null:
        (longest,) = connection.execute(f"SELECT max(length({column})) FROM {table}").fetchone()
        if longest is not None and longest <= MAX_CODE_LENGTH:
            stats.codes = [
                str(value) for (value,) in connection.execute(
                    f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL ORDER BY 1"
                ).fetchall()
            ]
