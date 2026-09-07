// AVA represents a donut as a pie with an inner radius, not a separate chart type.
export function requestsDonut(query) {
  const normalized = query
    .normalize("NFKC")
    .replace(/[\u064b-\u065f\u0670\u0640]/g, "");
  return /\b(?:donut|doughnut)\b|دونات|دونت/i.test(normalized);
}

export function donutSyntax(syntax) {
  const clean = syntax.trim().replace(/^```[^\n]*\n|\n```$/g, "");
  if (!/^vis\s+(?:pie|donut|doughnut)\s*$/m.test(clean)) {
    throw new Error(
      "AVA returned invalid donut syntax. Try the question again.",
    );
  }
  return (
    clean
      .replace(/^vis\s+(?:pie|donut|doughnut)\s*$/m, "vis pie")
      .replace(/^(?:innerRadius|theme)\s+.*(?:\r?\n|$)/gm, "")
      .trim() + "\ninnerRadius 0.6\ntheme dark"
  );
}

export function chartHTML(syntax) {
  // Use a JSON string literal and escape HTML delimiters; syntax is data, never script.
  const literal = JSON.stringify(syntax)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026");
  return `<!doctype html><html><head><meta charset="utf-8"><title>AVA visualization</title>
<script src="https://unpkg.com/@antv/gpt-vis/dist/umd/index.min.js"></script>
<style>html,body,#container{margin:0;width:100%;height:100%;background:#14181b;color:#eee;font-family:Arial,sans-serif}</style>
</head><body><div id="container"></div><script>
try { new GPTVis.GPTVis({container:'#container'}).render(${literal}); }
catch(error) { document.getElementById('container').textContent='Chart rendering failed: '+error.message; }
</script></body></html>`;
}

// Use AVA's actual advisor and generator, but don't swallow their exceptions.
export async function visualizeAnalysis(
  analysis,
  dataInfo,
  llm,
  { advise, generate },
) {
  if (
    analysis.data == null ||
    (Array.isArray(analysis.data) && !analysis.data.length)
  ) {
    throw new Error(
      "Analysis returned no data to visualize. Try asking for a category and a numeric measure.",
    );
  }
  const donut = requestsDonut(analysis.query);
  const query = `${analysis.query}\nUse the dark theme for the visualization.${donut ? "\nThe user explicitly requested a donut chart: use vis pie with innerRadius 0.6. Preserve all supplied categories and values." : ""}`;
  const chartType = donut ? "pie" : await advise(query, dataInfo, llm);
  if (!chartType) return null;
  const generated = await generate(chartType, analysis.data, query, llm);
  if (!donut) return { chartType, ...generated };
  const syntax = donutSyntax(generated.syntax);
  return { chartType: "pie (donut)", syntax, html: chartHTML(syntax) };
}
