import test from "node:test";
import assert from "node:assert/strict";
import { parseData, prepareData, sample } from "../src/data.js";
test("CSV quoted values, types and missing values", () => {
  assert.deepEqual(
    parseData(
      'region,revenue,note\n"North, east",42,"hello"\nSouth,,"ok"',
      "a.csv",
    ),
    [
      { region: "North, east", revenue: 42, note: "hello" },
      { region: "South", revenue: null, note: "ok" },
    ],
  );
});
test("TSV, JSON envelope and JSONL", () => {
  assert.equal(parseData("x\ty\n1\t2", "a.tsv")[0].y, 2);
  assert.equal(parseData('{"data":[{"x":1}]}', "a.json")[0].x, 1);
  assert.equal(parseData('{"x":1}\n{"x":2}', "a.jsonl").length, 2);
});
test("reject empty, malformed and unsupported uploads", () => {
  for (const [text, name] of [
    ["[]", "a.json"],
    ["[1]", "a.json"],
    ["{", "a.json"],
    ["x,y\n1,2,3", "a.csv"],
    ["x,x\n1,2", "a.csv"],
    ["hello", "a.xlsx"],
  ])
    assert.throws(() => parseData(text, name));
});
test("omit entire unsafe columns, preserve heterogeneous rows and nulls", () => {
  const result = prepareData([
    { x: 1, geometry: "POINT(1 2)", note: "short" },
    { x: 2, geometry: null, note: "x".repeat(1001), later: 4 },
  ]);
  assert.deepEqual(result.omitted, ["geometry", "note"]);
  assert.deepEqual(result.data, [
    { x: 1, later: null },
    { x: 2, later: 4 },
  ]);
});
test("sample has independently known regional totals", () => {
  const totals = Object.groupBy(sample, (r) => r.region);
  assert.deepEqual(
    Object.fromEntries(
      Object.entries(totals).map(([key, rows]) => [
        key,
        rows.reduce((n, r) => n + r.revenue, 0),
      ]),
    ),
    { North: 129450, South: 107250, East: 151050, West: 120450 },
  );
});
