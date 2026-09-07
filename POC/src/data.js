import Papa from "papaparse";
export const MAX_BYTES = 10 * 1024 * 1024;
export const sample = Array.from({ length: 24 }, (_, i) => ({
  month: `2025-${String(Math.floor(i / 4) + 1).padStart(2, "0")}-01`,
  region: ["North", "South", "East", "West"][i % 4],
  revenue: [18200, 14500, 21800, 16700][i % 4] + Math.floor(i / 4) * 1350,
  orders: [124, 98, 156, 113][i % 4] + Math.floor(i / 4) * 12,
}));
export function parseData(text, name) {
  const extension = name.split(".").pop().toLowerCase();
  let rows;
  if (extension === "json") {
    const parsed = JSON.parse(text);
    rows = Array.isArray(parsed) ? parsed : parsed.data;
  } else if (["jsonl", "ndjson"].includes(extension)) {
    rows = text
      .split(/\r?\n/)
      .filter((line) => line.trim())
      .map((line) => JSON.parse(line));
  } else if (["csv", "tsv"].includes(extension)) {
    const parsed = Papa.parse(text, {
      header: true,
      skipEmptyLines: "greedy",
      dynamicTyping: true,
      delimiter: extension === "tsv" ? "\t" : "",
    });
    const error = parsed.errors.find((e) => e.code !== "UndetectableDelimiter");
    if (error)
      throw new Error(`CSV row ${(error.row ?? 0) + 2}: ${error.message}`);
    if (parsed.meta.renamedHeaders)
      throw new Error(
        "Duplicate column names. Give each column a unique name.",
      );
    rows = parsed.data;
  } else throw new Error("Choose a CSV, TSV, JSON, JSONL, or NDJSON file.");
  if (
    !Array.isArray(rows) ||
    !rows.length ||
    rows.some((row) => !row || typeof row !== "object" || Array.isArray(row))
  )
    throw new Error(
      'Data must contain at least one row of objects. JSON can be an array or { "data": [...] }.',
    );
  return rows;
}
export function prepareData(rows) {
  const columns = [...new Set(rows.flatMap(Object.keys))];
  const omitted = columns.filter(
    (key) =>
      /wkt/i.test(key) ||
      rows.some((row) => {
        const value = row[key];
        return (
          value != null &&
          (JSON.stringify(value).length > 1000 ||
            (typeof value === "string" &&
              /^\s*(?:SRID=\d+;)?(?:POINT|LINESTRING|POLYGON|MULTIPOINT|MULTILINESTRING|MULTIPOLYGON|GEOMETRYCOLLECTION)\s*(?:Z?M?\s*)?(?:\(|EMPTY\b)/i.test(
                value,
              )))
        );
      }),
  );
  const safe = columns.filter((key) => !omitted.includes(key));
  if (!safe.length)
    throw new Error(
      "No analyzable columns remain after excluding WKT and oversized values.",
    );
  const data = rows.map((row) =>
    Object.fromEntries(
      safe.map((key) => [
        key,
        row[key] == null
          ? null
          : typeof row[key] === "object"
            ? JSON.stringify(row[key])
            : row[key],
      ]),
    ),
  );
  return { data, columns: safe, omitted, rowCount: rows.length };
}
