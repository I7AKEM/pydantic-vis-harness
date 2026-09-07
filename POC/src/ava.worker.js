import { AVA, extractMetadata, formatDatasetInfo } from "@antv/ava";
import {
  adviseChartType,
  generateVisualizationHTML,
} from "@antv/ava/esm/visualization/index.js";
import { visualizeAnalysis } from "./visualization.js";

self.onmessage = async ({ data: { rows, query, config, action } }) => {
  const llm = {
    model: config.model,
    apiKey: "local-proxy",
    baseURL: config.baseURL,
  };
  const ava = new AVA({
    llm,
    sqlThreshold: Number.MAX_SAFE_INTEGER,
  });
  try {
    await ava.loadObject(rows);
    if (action === "suggest") {
      self.postMessage({ type: "suggestions", value: await ava.suggest(3) });
    } else {
      self.postMessage({ type: "stage", value: "Analyzing your data" });
      const analysis = await ava.analysis(`${query}

Implementation requirements: This stage computes data only. Return JSON-serializable data rows or scalar values. Do not return chart configurations, callbacks, functions, HTML, or rendering code. A separate visualization stage will draw the requested chart. Preserve the numeric measurements and all relevant categories. Write the summary in the language of the user's question and do not claim a chart has already been rendered.`);
      analysis.query = query;
      // Fail visibly rather than losing the whole result to a structured-clone error.
      JSON.stringify(analysis.data, (_key, value) => {
        if (
          typeof value === "function" ||
          typeof value === "bigint" ||
          typeof value === "symbol"
        ) {
          throw new Error(
            "AVA returned executable chart configuration instead of result data. Please retry the question.",
          );
        }
        return value;
      });
      self.postMessage({ type: "analysis", value: analysis });
      self.postMessage({
        type: "stage",
        value: "Choosing and building a chart",
      });
      try {
        const dataInfo = Array.isArray(analysis.data)
          ? formatDatasetInfo(extractMetadata(analysis.data))
          : JSON.stringify(analysis.data);
        const visualization = await visualizeAnalysis(analysis, dataInfo, llm, {
          advise: adviseChartType,
          generate: generateVisualizationHTML,
        });
        self.postMessage({ type: "done", value: visualization });
      } catch (error) {
        self.postMessage({
          type: "chart-error",
          value: error.message || String(error),
        });
      }
    }
  } catch (error) {
    self.postMessage({ type: "error", value: error.message || String(error) });
  } finally {
    ava.dispose();
  }
};
