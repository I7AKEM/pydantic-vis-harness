# AVA Playground

A standalone dark React POC for the [AntV AVA](https://github.com/antvis/AVA) conversational data-analysis API. Uses the published `@antv/ava@4.0.0-alpha.1` release; npm's stable 3.x release has a different API.

## Run

Requires Node.js 20.19+ or 22.12+.

```sh
cd POC
npm ci --ignore-scripts
npm run dev
```

Open http://127.0.0.1:5174. The development server reads `OPENROUTER_API_KEY` from `POC/.env`, the parent project's `.env`, or the shell environment. Shell variables take precedence. `AVA_MODEL` overrides the model; otherwise the parent's `PYDANTIC_AI_MODEL` is used (without its `openrouter:` prefix), falling back to `anthropic/claude-sonnet-4.6`. Restart after changing environment variables. No API key is exposed in the client bundle.

Use **Use sample data**, or upload a CSV, TSV, JSON, JSONL, or NDJSON file (up to 10 MB). JSON accepts an array of row objects or `{ "data": [...] }`. Nested cell values are serialized as JSON strings. XLSX, PDF, images, and arbitrary binary files are not supported; export tabular files to CSV first.

Ask a question and inspect **Visualization**, **Result data**, and **Generated code**. **Suggest with AVA** asks AVA for three dataset-specific questions. The initial prompt chips are local examples. Each question is independent, not a multi-turn chat. Use **Stop** to terminate the worker; a model request already sent may still finish and incur usage.

## What actually runs

1. Parse and validate the upload locally. Exclude whole columns containing WKT or any value over 1,000 serialized characters before sending data to AVA. The interface reports excluded column names and counts.
2. Run the real `AVA.loadObject()` in a fresh browser worker, using the in-memory path for this bounded POC.
3. Call `AVA.analysis(question)` with data-only output requirements. AVA generates and executes JavaScript over the data and summarizes the result. The POC rejects non-serializable results such as chart callbacks before transferring them from the worker; chart rendering belongs to the next stage.
4. Call AVA's chart advisor and visualization generator with a dark-theme instruction. These are the same modules used by `AVA.visualize`, but called directly so errors are surfaced. Explicit Arabic/English donut requests bypass automatic type selection and use `pie` with `innerRadius 0.6`; the generated syntax is wrapped in a sandboxed GPT-Vis iframe. Other chart types use AVA's generated HTML. Chart rendering loads GPT-Vis from unpkg and needs internet access.
5. Suggestions call `AVA.suggest(3)`.

The Vite middleware proxies only chat-completion requests to OpenRouter using the server-side key and configured model. Uploads remain in browser memory and disappear on reload. Dataset samples and analysis results go to OpenRouter and the selected model provider; normal API usage charges apply. There is no persistence or Python integration.

## Checks

```sh
npm test
npm run build
```

The tests also cover Arabic/English donut selection, radius/theme normalization, surfaced generation failures, empty data, and safe chart embedding. The data tests cover typed CSV parsing, quoted cells, TSV/JSON/JSONL, invalid uploads, whole-column omission, heterogeneous rows, and known sample totals. Browser verification exercised a real OpenRouter analysis and rendered dark chart, matching regional totals: North 129,450; South 107,250; East 151,050; West 120,450. A CSV upload with a WKT column was also verified.

`npm run build` validates the client bundle; this is a local development POC and the API middleware is only provided by `npm run dev`. Serving `dist/` alone will not provide analysis.

## Boundaries

AVA is alpha software and executes model-generated JavaScript. The worker prevents that code from executing in Node or directly accessing the page DOM, and allows timeout/cancellation; it is not a complete security sandbox. Generated chart HTML has scripts enabled but no same-origin permission. Do not publicly expose this local development server. AVA can select no chart; the UI reports that separately from a generation failure and retains the analysis and result data. The POC calls the generation modules directly to avoid AVA's catch-and-return-null behavior. Results depend on the model and should be inspected.

AVA currently brings older AI SDK dependencies: the dependency audit reports low/moderate advisories and a high-severity `jsondiffpatch` advisory in the upstream dependency tree. This POC does not call its patch/HTML formatter APIs. Upgrading AVA's entire SDK stack is outside this POC.

The browser build aliases AVA's `csv-parse/sync` import to its official browser entry point. Native SQLite installation scripts are skipped because this POC uses browser memory. The existing Python application is unchanged.
