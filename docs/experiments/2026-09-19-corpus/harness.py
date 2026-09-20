"""Model-free pass over the 500 Dev CSVs: upload -> direct read -> shape -> deterministic chart recommendation."""
import csv, json, sys, time, traceback
from pathlib import Path

from vis_agent.analyst.source import SourceUnavailable, load_csv_report
from vis_agent.designer.recommend import recommend_charts
from vis_agent.store import DatasetStore

CORPUS = Path("/Users/muhammad/Desktop/Dev CSV")
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "results.jsonl"
work = OUT.parent / "store"
work.mkdir(parents=True, exist_ok=True)
store = DatasetStore(work)  # production default: 20 MB upload limit

rows = list(csv.DictReader(open(CORPUS / "manifest.csv")))
with OUT.open("w") as out:
    for i, row in enumerate(rows):
        rec = {"id": row["dataset_id"], "shape": row["data_shapes"], "row_bucket": row["row_bucket"],
               "edge": row["edge_cases"], "upstream_charts": row["chart_types"], "question": row["primary_question"][:120]}
        meta = json.load(open(CORPUS / row["metadata_path"]))
        question = row["primary_question"] or "اعرض البيانات"
        started = time.perf_counter()
        try:
            content = (CORPUS / row["csv_path"]).read_bytes()
            rec["bytes"] = len(content)
            try:
                ds = store.save_upload(f"{row['dataset_id']}.csv", content).dataset_id
            except Exception as exc:  # upload refused
                rec.update(status="upload_refused", error=f"{type(exc).__name__}: {exc}"[:200])
                out.write(json.dumps(rec, ensure_ascii=False) + "\n"); continue
            try:
                report = load_csv_report(store, ds, question)
            except SourceUnavailable as exc:
                rec.update(status="source_unavailable", error=str(exc)[:200])
                out.write(json.dumps(rec, ensure_ascii=False) + "\n"); continue
            cols = report.analysis.columns
            rec.update(status="ok", rows=report.result.row_count, cols=len(cols),
                       kinds={c.name: c.kind for c in cols}, types=report.result.types,
                       omitted=[w for w in report.warnings], language=report.language)
            rec["measures"] = sum(1 for c in cols if c.kind == "measure")
            rec["categories"] = sum(1 for c in cols if c.kind == "category")
            rec["times"] = sum(1 for c in cols if c.kind == "time")
            try:
                recommendation = recommend_charts(cols, report.result)
                rec["candidates"] = [(c.name, round(c.score, 2)) for c in recommendation.candidates[:4]]
                rec["n_candidates"] = len(recommendation.candidates)
                if not recommendation.candidates:
                    rec["rejections"] = [(r.name, r.rule, r.explanation[:100]) for r in recommendation.rejected[:6]]
            except Exception as exc:
                rec.update(recommend_error=f"{type(exc).__name__}: {exc}"[:300])
        except Exception as exc:
            rec.update(status="error", error=f"{type(exc).__name__}: {exc}"[:300], trace=traceback.format_exc()[-600:])
        rec["seconds"] = round(time.perf_counter() - started, 2)
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if i % 50 == 0:
            print(i, rec["id"], rec.get("status"), file=sys.stderr, flush=True)
print("done", len(rows), file=sys.stderr)
