"""Pick diverse corpus files, copy them into a cases directory, and write briefs from the sidecars.

    uv run python evals/profiler/corpus_tools/select_cases.py CORPUS_DIR OUT_DIR SEED [EXCLUDE_DIR ...]

Quotas per data shape are scaled from the shape counts below; edit them for a different size.
"""
import csv, json, random, shutil, sys
from collections import defaultdict
from pathlib import Path
from vis_agent.models import DataBrief
D = Path(sys.argv[1]); OUT = Path(sys.argv[2]); OUT.mkdir(exist_ok=True); SEED = int(sys.argv[3])
USED = {p.stem for d in sys.argv[4:] for p in Path(d).glob("*.csv")}
rows = [r for r in csv.DictReader(open(D / "manifest.csv", encoding="utf-8"))
        if int(r["decoded_bytes"]) <= 1_000_000 and int(r["parsed_row_count"]) >= 1 and int(r["parsed_column_count"]) >= 1 and r["dataset_id"] not in USED]
QUOTA = {"multi_column_table": 51, "two_column_series": 34, "single_row_wide": 26, "wide_table": 24, "very_wide_table": 4, "single_column_list": 6, "scalar": 8}
by_shape = defaultdict(list)
for r in rows: by_shape[r["data_shapes"]].append(r)
rng = random.Random(SEED); chosen = []
for shape, n in QUOTA.items():
    pool = by_shape.get(shape, []); rng.shuffle(pool)
    # round-robin over (row bucket, edge cases) so buckets and edge cases spread out
    groups = defaultdict(list)
    for r in pool: groups[(r["row_bucket"], r["edge_cases"])].append(r)
    keys = sorted(groups); picked = []
    while len(picked) < min(n, len(pool)):
        for k in keys:
            if groups[k] and len(picked) < n: picked.append(groups[k].pop())
    chosen += picked
selection = {}
for r in chosen:
    did = r["dataset_id"]; shutil.copy(D / r["csv_path"], OUT / f"{did}.csv")
    side = json.loads((D / r["metadata_path"]).read_text(encoding="utf-8")); occ = side["occurrences"][0]
    fields = {"source": "insightor", "producer_agent": "insightor",
              "query": occ.get("executed_sql") or occ.get("original_sql"),
              "raw_question": occ.get("conversation_title") or r["primary_question"] or None,
              "enriched_question": occ.get("enriched_or_resolved_question"),
              "suggested_chart_type": (r["chart_types"].split(";")[0] if r["chart_types"] else None)}
    intent = occ.get("orchestrator_intent")
    TASKS = {"compare": "compare", "comparison": "compare", "trend": "trend", "rank": "rank", "ranking": "rank",
             "distribution": "distribution", "composition": "composition", "relation": "relation", "relationship": "relation",
             "correlation": "relation", "share": "share", "proportion": "share", "part_to_whole": "share"}
    task = intent.get("task") if isinstance(intent, dict) else intent
    if isinstance(task, str):
        if task.lower() in TASKS: fields["intent"] = TASKS[task.lower()]
        else: print("unmapped intent task:", task)
    fields = {k: (v[:4000] if isinstance(v, str) else v) for k, v in fields.items() if v}
    brief = DataBrief.model_validate(fields)
    (OUT / f"{did}.brief.json").write_text(brief.model_dump_json(exclude_none=True, indent=2), encoding="utf-8")
    selection[did] = {"shape": r["data_shapes"], "rows": int(r["parsed_row_count"]), "columns": int(r["parsed_column_count"]),
                      "row_bucket": r["row_bucket"], "edge_cases": r["edge_cases"], "domains": r["domains"], "bytes": int(r["decoded_bytes"])}
(OUT / "selection.json").write_text(json.dumps(selection, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"selected {len(chosen)} files; shapes: { {s: sum(1 for v in selection.values() if v['shape']==s) for s in QUOTA} }")
print(f"total bytes copied: {sum(v['bytes'] for v in selection.values()):,}; columns total: {sum(v['columns'] for v in selection.values())}")
print("row buckets:", {b: sum(1 for v in selection.values() if v['row_bucket']==b) for b in sorted({v['row_bucket'] for v in selection.values()})})
