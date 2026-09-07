import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ArrowUp,
  ArrowUpRight,
  BarChart3,
  Braces,
  Check,
  ChevronRight,
  Database,
  FileText,
  FlaskConical,
  LoaderCircle,
  Plus,
  Sparkles,
  Table2,
  Upload,
  X,
} from "lucide-react";
import { MAX_BYTES, parseData, prepareData, sample } from "./data";
import "./style.css";

const starters = [
  "Show total revenue by region as a bar chart",
  "How has revenue changed over time?",
  "Which region has the highest revenue per order?",
];
function App() {
  const [dataset, setDataset] = useState(null),
    [name, setName] = useState("");
  const [query, setQuery] = useState(""),
    [asked, setAsked] = useState("");
  const [config, setConfig] = useState(null),
    [error, setError] = useState("");
  const [busy, setBusy] = useState(""),
    [analysis, setAnalysis] = useState(null),
    [viz, setViz] = useState(null);
  const [chartStatus, setChartStatus] = useState("idle");
  const [suggestions, setSuggestions] = useState([]),
    [tab, setTab] = useState("chart"),
    [drag, setDrag] = useState(false);
  const worker = useRef(null),
    timer = useRef(null),
    fileInput = useRef(null);
  useEffect(() => {
    fetch("/api/config")
      .then((r) => r.json())
      .then(setConfig)
      .catch(() =>
        setError(
          "Cannot connect to the local API. Start the app with npm run dev.",
        ),
      );
    return () => {
      worker.current?.terminate();
      clearTimeout(timer.current);
    };
  }, []);
  function stop() {
    worker.current?.terminate();
    worker.current = null;
    clearTimeout(timer.current);
    setBusy("");
    setChartStatus((current) => (current === "pending" ? "stopped" : current));
  }
  function load(rows, filename) {
    const next = prepareData(rows);
    stop();
    setDataset(next);
    setName(filename);
    setAnalysis(null);
    setViz(null);
    setAsked("");
    setError("");
    setSuggestions([]);
    setQuery("");
  }
  async function upload(file) {
    if (!file) return;
    try {
      if (file.size > MAX_BYTES)
        throw new Error("This browser POC supports files up to 10 MB.");
      load(parseData(await file.text(), file.name), file.name);
    } catch (e) {
      setError(e.message);
    }
  }
  function run(action = "analyze", question = query) {
    if (!dataset || busy || (action === "analyze" && !question.trim())) return;
    if (!config?.configured) {
      setError(
        "Add OPENROUTER_API_KEY to POC/.env or the project .env, then restart npm run dev.",
      );
      return;
    }
    setError("");
    setBusy(
      action === "suggest" ? "Finding good questions" : "Analyzing your data",
    );
    if (action === "analyze") {
      setAnalysis(null);
      setViz(null);
      setChartStatus("pending");
      setAsked(question.trim());
      setTab("chart");
    }
    const w = new Worker(new URL("./ava.worker.js", import.meta.url), {
      type: "module",
    });
    worker.current = w;
    timer.current = setTimeout(() => {
      stop();
      setError(
        "AVA timed out after 3 minutes. Try a simpler question or a smaller dataset.",
      );
    }, 180000);
    w.onerror = (event) => {
      setError(
        event.message || "AVA could not start. Check the terminal for details.",
      );
      stop();
    };
    w.onmessage = ({ data }) => {
      if (data.type === "stage") setBusy(data.value);
      if (data.type === "analysis") setAnalysis(data.value);
      if (data.type === "suggestions") {
        setSuggestions(data.value);
        stop();
      }
      if (data.type === "done") {
        setChartStatus(data.value ? "complete" : "none");
        setViz(data.value);
        if (!data.value) setTab("data");
        stop();
      }
      if (data.type === "chart-error") {
        setChartStatus("failed");
        setError(`Chart generation failed: ${data.value}`);
        stop();
      }
      if (data.type === "error") {
        setError(data.value);
        stop();
      }
    };
    w.postMessage({
      action,
      query: question.trim(),
      rows: dataset.data,
      config: { ...config, baseURL: `${location.origin}/api/llm` },
    });
  }
  const prompts = suggestions.length
    ? suggestions.map((s) => s.query)
    : name === "regional-sales.csv"
      ? starters
      : [
          "Summarize this dataset and its key patterns",
          "Show an informative chart of this data",
          "Find the largest differences in this data",
        ];
  return (
    <div className="app">
      <aside>
        <a className="brand" href="/" aria-label="AVA home">
          <span className="brand-icon">
            <BarChart3 size={22} />
          </span>
          ava<span className="brand-dot">.</span>
          <span className="lab">PLAYGROUND</span>
        </a>
        <div className="side-label">WORKSPACE</div>
        <div className="nav-item">
          <FlaskConical size={17} /> Data explorer <span>01</span>
        </div>
        <div className="side-heading">
          <span className="side-label">YOUR DATA</span>
          <button
            className="icon-button"
            aria-label="Upload data"
            disabled={!!busy}
            onClick={() => fileInput.current.click()}
          >
            <Plus size={16} />
          </button>
        </div>
        <button
          className={`upload-zone ${drag ? "drag" : ""}`}
          disabled={!!busy}
          onClick={() => fileInput.current.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            if (!busy) upload(e.dataTransfer.files[0]);
          }}
        >
          <span className="upload-icon">
            <Upload size={20} />
          </span>
          <strong>Drop your data here</strong>
          <span>or click to browse files</span>
          <small>CSV, TSV, JSON, JSONL · up to 10 MB</small>
        </button>
        <input
          ref={fileInput}
          hidden
          type="file"
          accept=".csv,.tsv,.json,.jsonl,.ndjson"
          onChange={(e) => {
            upload(e.target.files[0]);
            e.target.value = "";
          }}
        />
        {dataset ? (
          <div className="dataset-card">
            <div>
              <FileText size={17} />
              <strong title={name}>{name}</strong>
              <Check size={15} className="green" />
            </div>
            <p>
              {dataset.rowCount.toLocaleString()} rows <span>·</span>{" "}
              {dataset.columns.length} columns
            </p>
            <div className="column-list">
              {dataset.columns.slice(0, 12).map((c) => (
                <span key={c}>
                  {typeof dataset.data.find((r) => r[c] != null)?.[c] ===
                  "number"
                    ? "#"
                    : "Aa"}{" "}
                  <b>{c}</b>
                </span>
              ))}
              {dataset.columns.length > 12 && (
                <small>+{dataset.columns.length - 12} more columns</small>
              )}
            </div>
          </div>
        ) : (
          <p className="side-hint">Your uploaded dataset will appear here.</p>
        )}
        <div className="sidebar-bottom">
          <span className="status-dot" />{" "}
          {config?.configured
            ? "OpenRouter connected"
            : "OpenRouter key needed"}
          <small title={config?.model}>{config?.model || "Connecting…"}</small>
          <a
            href="https://github.com/antvis/AVA"
            target="_blank"
            rel="noreferrer"
          >
            Built with AntV AVA <ArrowUpRight size={14} />
          </a>
        </div>
      </aside>
      <main>
        <header>
          <span>
            Workspace <ChevronRight size={14} /> <b>Data explorer</b>
          </span>
          <span className="version">
            AVA 4.0 alpha <i /> Local POC
          </span>
        </header>
        <div className="content">
          <div className="eyebrow">
            <span /> FROM DATA TO DISCOVERY
          </div>
          <h1>Your data. A new perspective.</h1>
          <p className="intro">
            Upload a dataset, ask a question, and see how AVA brings it to life.
          </p>
          <div className="steps">
            <span className={dataset ? "complete" : "active"}>
              <i>{dataset ? <Check size={13} /> : "1"}</i> Add data
            </span>
            <div />
            <span className={dataset ? "active" : ""}>
              <i>2</i> Ask anything
            </span>
            <div />
            <span className={analysis ? "active" : ""}>
              <i>3</i> Explore the result
            </span>
          </div>
          {!dataset && (
            <section className="sample-card">
              <div className="sample-art">
                <BarChart3 size={32} />
              </div>
              <div>
                <span className="mini-label">A QUICK START</span>
                <h3>Meet your next insight.</h3>
                <p>Try six months of regional sales, ready to explore.</p>
              </div>
              <button
                className="secondary"
                onClick={() => load(sample, "regional-sales.csv")}
              >
                Use sample data <ArrowUpRight size={16} />
              </button>
            </section>
          )}
          <section className="question-card">
            <div className="question-label">
              <Sparkles size={17} />
              <span>What would you like to know?</span>
              {dataset && (
                <small>
                  <Database size={12} />
                  {name}
                </small>
              )}
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                run();
              }}
            >
              <textarea
                aria-label="Question about your data"
                dir="auto"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={
                  dataset
                    ? "Compare categories, uncover trends, or ask for a chart…"
                    : "Add your data to start exploring…"
                }
                disabled={!dataset || !!busy}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    run();
                  }
                }}
              />
              <div className="question-footer">
                <span>Powered by AVA · analysis + visualization</span>
                {busy ? (
                  <button type="button" className="secondary" onClick={stop}>
                    <X size={14} /> Stop
                  </button>
                ) : (
                  <button
                    className="send"
                    aria-label="Ask AVA"
                    disabled={!dataset || !query.trim()}
                  >
                    <ArrowUp size={19} />
                  </button>
                )}
              </div>
            </form>
          </section>
          {dataset && (
            <div className="suggestions">
              <div>
                {prompts.map((p) => (
                  <button key={p} disabled={!!busy} onClick={() => setQuery(p)}>
                    {p}
                    <ArrowUpRight size={13} />
                  </button>
                ))}
              </div>
              <button
                className="text-button"
                disabled={!!busy}
                onClick={() => run("suggest")}
              >
                <Sparkles size={13} /> Suggest with AVA
              </button>
            </div>
          )}
          <p className="privacy">
            Questions send dataset samples and analysis results to the
            configured model through OpenRouter. Files stay in browser memory.
          </p>
          {dataset?.omitted.length > 0 && (
            <div className="notice">
              Excluded {dataset.omitted.length} columns containing WKT or values
              over 1,000 characters: {dataset.omitted.join(", ")}. These values
              are not sent to AVA.
            </div>
          )}
          {error && (
            <div className="error" role="alert">
              <strong>Something needs attention</strong>
              <p>{error}</p>
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {busy && (
            <div className="loading" role="status">
              <LoaderCircle size={18} />
              {busy}
              <span>AVA is working on it</span>
            </div>
          )}
          {analysis ? (
            <section className="result">
              <div className="result-title">
                <span className="spark-icon">
                  <Sparkles size={17} />
                </span>
                <div>
                  <span className="mini-label">AVA'S ANSWER</span>
                  <h3>{asked}</h3>
                </div>
                {!busy && (
                  <span className="done">
                    {chartStatus === "complete"
                      ? "Complete"
                      : chartStatus === "failed"
                        ? "Chart failed"
                        : chartStatus === "stopped"
                          ? "Stopped"
                          : "No chart selected"}
                  </span>
                )}
              </div>
              <div className="markdown" dir="auto">
                <Markdown remarkPlugins={[remarkGfm]}>{analysis.text}</Markdown>
              </div>
              <div className="tabs">
                {[
                  ["chart", BarChart3, "Visualization"],
                  ["data", Table2, "Result data"],
                  ["code", Braces, "Generated code"],
                ].map(([key, Icon, label]) => (
                  <button
                    className={tab === key ? "selected" : ""}
                    key={key}
                    onClick={() => setTab(key)}
                  >
                    <Icon size={15} />
                    {label}
                  </button>
                ))}
                {viz && <span>{viz.chartType}</span>}
              </div>
              <div className="result-body">
                {tab === "chart" ? (
                  viz ? (
                    <iframe
                      title="AVA generated visualization"
                      sandbox="allow-scripts"
                      referrerPolicy="no-referrer"
                      srcDoc={viz.html}
                    />
                  ) : (
                    <div className="no-chart">
                      <BarChart3 size={28} />
                      <p>
                        {busy
                          ? "AVA is preparing the visualization…"
                          : chartStatus === "failed"
                            ? "Chart generation failed. The error above explains why; your analysis is still available."
                            : chartStatus === "stopped"
                              ? "Visualization was stopped before it finished."
                              : "AVA did not select a supported chart type. Try naming the chart you want."}
                      </p>
                    </div>
                  )
                ) : (
                  <pre>
                    {tab === "data"
                      ? (JSON.stringify(analysis.data, null, 2) ??
                        "No result data returned.")
                      : analysis.code ||
                        analysis.sql ||
                        "AVA returned no code."}
                  </pre>
                )}
              </div>
              {viz && (
                <details>
                  <summary>Inspect AVA chart syntax</summary>
                  <pre>
                    {typeof viz.syntax === "string"
                      ? viz.syntax
                      : JSON.stringify(viz.syntax, null, 2)}
                  </pre>
                </details>
              )}
            </section>
          ) : (
            !busy && (
              <div className="empty-state">
                <div>
                  <BarChart3 size={25} />
                </div>
                <h3>A little curiosity goes a long way.</h3>
                <p>
                  Your answer, visualization, and the code behind it will appear
                  here.
                </p>
              </div>
            )
          )}
          {dataset && (
            <section className="preview">
              <div className="preview-heading">
                <h3>
                  <Table2 size={16} /> Data preview
                </h3>
                <span>
                  First {Math.min(5, dataset.rowCount)} of{" "}
                  {dataset.rowCount.toLocaleString()} rows
                </span>
              </div>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      {dataset.columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {dataset.data.slice(0, 5).map((row, i) => (
                      <tr key={i}>
                        {dataset.columns.map((c) => (
                          <td key={c}>
                            {row[c] == null ? (
                              <span className="muted">null</span>
                            ) : (
                              String(row[c])
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          <footer>
            <span>AVA PLAYGROUND</span>
            <span>Explore · Understand · Visualize</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")).render(<App />);
