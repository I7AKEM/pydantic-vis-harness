import test from "node:test";
import assert from "node:assert/strict";
import {
  requestsDonut,
  visualizeAnalysis,
  chartHTML,
} from "../src/visualization.js";

test("Arabic and English donut requests use pie without asking the selector", async () => {
  for (const query of [
    "اعرضهم في دونات",
    "اعرضهم في دُونَات",
    "Show a doughnut",
    "donut chart",
  ]) {
    assert.equal(requestsDonut(query), true);
    const data = [{ district: "الحمراء", count: 210 }];
    const result = await visualizeAnalysis(
      { query, data },
      "",
      {},
      {
        advise() {
          assert.fail("Explicit donut must bypass the type advisor");
        },
        async generate(type, supplied, prompt) {
          assert.equal(type, "pie");
          assert.equal(supplied, data);
          assert.match(prompt, /innerRadius 0.6/);
          return {
            syntax:
              "vis pie\ndata\n  - category الحمراء\n    value 210\ninnerRadius 0\ntheme default",
            html: "unused",
          };
        },
      },
    );
    assert.match(result.syntax, /innerRadius 0.6\ntheme dark$/);
    assert.equal(result.syntax.match(/innerRadius/g).length, 1);
    assert.match(result.html, /value 210/);
  }
});
test("automatic recommendations still use AVA and surface generator errors", async () => {
  const analysis = { query: "show a trend", data: [1] };
  assert.equal(
    await visualizeAnalysis(analysis, "", {}, { advise: async () => null }),
    null,
  );
  await assert.rejects(
    visualizeAnalysis(
      analysis,
      "",
      {},
      {
        advise: async () => "line",
        generate: async () => {
          throw new Error("Provider timeout");
        },
      },
    ),
    /Provider timeout/,
  );
});
test("empty results and invalid donut syntax fail visibly", async () => {
  await assert.rejects(
    visualizeAnalysis({ query: "donut", data: [] }, "", {}, {}),
    /no data/,
  );
  await assert.rejects(
    visualizeAnalysis(
      { query: "donut", data: [1] },
      "",
      {},
      {
        generate: async () => ({ syntax: "not chart syntax" }),
      },
    ),
    /invalid donut syntax/,
  );
});
test("chart syntax cannot close the embedded script", () => {
  const html = chartHTML("vis pie\ntitle </script><script>alert(1)</script>");
  assert.equal(html.match(/<script>/g).length, 1);
  assert.match(html, /\\u003c\/script\\u003e/);
});
