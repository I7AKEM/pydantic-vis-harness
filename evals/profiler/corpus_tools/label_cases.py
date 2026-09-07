"""Candidate role labels from strong models, plus per-column facts for adjudication.

    uv run python evals/profiler/corpus_tools/label_cases.py OUT_DIR CASES_DIR openrouter:MODEL [openrouter:MODEL ...]
"""
import asyncio, json, sys, tempfile
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path.cwd() / ".env")
from vis_agent.store import DatasetStore
from vis_agent.models import DataBrief
from vis_agent.profiler.agent import create_profiler, profile_dataset
OUT = Path(sys.argv[1]); CASES = Path(sys.argv[2]); MODELS = sys.argv[3:]
names = sorted(p.stem for p in CASES.glob("*.csv"))

async def run_model(model):
    profiler = create_profiler(model); store = DatasetStore(Path(tempfile.mkdtemp()))
    labels, columns, sem = {}, {}, asyncio.Semaphore(6)
    async def one(name):
        async with sem:
            bp = CASES / f"{name}.brief.json"
            brief = DataBrief.model_validate_json(bp.read_text()) if bp.exists() else None
            ds = store.save_upload(f"{name}.csv", (CASES / f"{name}.csv").read_bytes(), brief)
            prof = await profile_dataset(store, profiler, ds.dataset_id)
            labels[name] = {c.name: {"role": c.role, "unit": c.unit} for c in prof.semantic.columns} if prof.semantic else None
            columns[name] = {c.name: {"type": c.physical_type, "distinct": c.distinct_count, "nulls": c.null_count,
                                      "levels": c.measurement_levels, "geo": c.geographic_role,
                                      "common": [v.value[:25] for v in c.common_values[:3]],
                                      "range": [c.numeric.minimum, c.numeric.maximum] if c.numeric else None,
                                      "omitted": c.values_omitted} for c in prof.deterministic.columns}
            columns[name]["_rows"] = prof.deterministic.row_count
            (OUT / f"labels-{model.split('/')[-1]}.json").write_text(json.dumps(labels, ensure_ascii=False, indent=1))
            (OUT / "columns.json").write_text(json.dumps(columns, ensure_ascii=False, indent=1))
    await asyncio.gather(*(one(n) for n in names))
    print(model, "done:", sum(1 for v in labels.values() if v), "of", len(names))

async def main():
    await asyncio.gather(*(run_model(m) for m in MODELS))
asyncio.run(main())
