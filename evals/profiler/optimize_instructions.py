"""Optimize the profiler's instruction text for the target model with DSPy GEPA. Pydantic AI stays the runtime;
only the resulting instruction text is pasted into PROFILER_INSTRUCTIONS in profiler.py, then measured with
evals/profiler/run.py on cases the optimizer never saw. Needs the optional dependency group: uv sync --group optimize

    uv run python -m evals.profiler.optimize_instructions check
    uv run python -m evals.profiler.optimize_instructions run light OUT_DIR   # or medium

Models come from PYDANTIC_AI_PROFILER_MODEL (task model, default from profiler.py) and OPTIMIZE_REFLECTION_MODEL
(default anthropic/claude-sonnet-4.6). Training uses evals/profiler/corpus_train, split 110 train / 40 dev.
"""
import json, os, random, sys, tempfile, time
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv; load_dotenv(Path.cwd() / ".env")
import dspy
from pydantic import BaseModel
from vis_agent.store import DatasetStore
from vis_agent.profiler.measurements import compute_statistics
from vis_agent.models import DataBrief
from vis_agent.profiler.agent import DEFAULT_PROFILER_MODEL, PROFILER_INSTRUCTIONS, ProfilerInput
EVALS = Path(__file__).parent
KEY = os.environ["OPENROUTER_API_KEY"]
TASK_MODEL = (os.getenv("PYDANTIC_AI_PROFILER_MODEL") or DEFAULT_PROFILER_MODEL).removeprefix("openrouter:")
REFLECTION_MODEL = os.getenv("OPTIMIZE_REFLECTION_MODEL", "anthropic/claude-sonnet-4.6")
task_lm = dspy.LM(f"openrouter/{TASK_MODEL}", api_key=KEY, temperature=0.0, max_tokens=6000, extra_body={"reasoning": {"effort": "none"}})
reflection_lm = dspy.LM(f"openrouter/{REFLECTION_MODEL}", api_key=KEY, temperature=1.0, max_tokens=16000)
dspy.configure(lm=task_lm)

Role = Literal["identifier", "measure", "category", "ordinal", "time", "boolean", "geography", "text", "unknown"]
class ColumnOut(BaseModel):
    name: str
    role: Role
    unit: str | None = None
    meaning: str | None = None
class ProfileOut(BaseModel):
    columns: list[ColumnOut]
class ProfileSig(dspy.Signature):
    statistics: str = dspy.InputField(desc="JSON with measured statistics for every column, sample rows, and the brief")
    profile: ProfileOut = dspy.OutputField(desc="exactly one entry per input column, using the column's exact name")
ProfileSig = ProfileSig.with_instructions(PROFILER_INSTRUCTIONS.strip())

class Profiler(dspy.Module):
    def __init__(self): super().__init__(); self.predict = dspy.Predict(ProfileSig)
    def forward(self, statistics): return self.predict(statistics=statistics)

def build_prompts(cases_dir: Path) -> dict[str, str]:
    """The exact prompt the profiler would send for each case: DuckDB statistics plus the brief. No model is called."""
    store = DatasetStore(Path(tempfile.mkdtemp(prefix="optimize-"))); prompts = {}
    for csv in sorted(cases_dir.glob("*.csv")):
        bp = cases_dir / f"{csv.stem}.brief.json"; brief = DataBrief.model_validate_json(bp.read_text()) if bp.exists() else None
        ds = store.save_upload(csv.name, csv.read_bytes(), brief); src = store.import_csv(ds.dataset_id)
        prompts[csv.stem] = ProfilerInput(statistics=compute_statistics(store, src), brief=src.brief).prompt_json()
    return prompts

def load(split_dir):
    cases_dir = EVALS / split_dir; prompts = build_prompts(cases_dir); expected = json.loads((cases_dir / "expected.json").read_text(encoding="utf-8"))
    return [dspy.Example(name=n, statistics=prompts[n], roles=expected[n]["roles"]).with_inputs("statistics") for n in sorted(expected) if n in prompts]

def facts(statistics_json, col):
    for c in json.loads(statistics_json)["statistics"]["columns"]:
        if c["name"] == col:
            keep = {k: c.get(k) for k in ("physical_type", "distinct_count", "null_count", "measurement_levels", "geographic_role", "codes", "ordinal_pattern", "boolean_vocabulary", "values_omitted")}
            keep["common_values"] = [v["value"][:30] for v in c.get("common_values", [])[:3]]
            return json.dumps({k: v for k, v in keep.items() if v not in (None, [], False)}, ensure_ascii=False)
    return "{}"

def score_and_feedback(gold, pred):
    try: got = {c.name: c.role for c in pred.profile.columns}
    except Exception as e: return 0.0, f"The output could not be parsed as a profile: {type(e).__name__}. Return exactly one entry per column."
    exp = gold.roles; correct = sum(got.get(n) == r for n, r in exp.items()); score = correct / len(exp)
    lines = [f"{n}: expected {r}, got {got.get(n)}; facts {facts(gold.statistics, n)}" for n, r in exp.items() if got.get(n) != r]
    extra = set(got) - set(exp)
    if extra: lines.append(f"extra columns that do not exist: {sorted(extra)}")
    return score, ("All roles correct." if not lines else "Wrong roles:\n" + "\n".join(lines))

def metric(gold, pred, trace=None, pred_name=None, pred_trace=None):
    score, fb = score_and_feedback(gold, pred); return dspy.Prediction(score=score, feedback=fb)
def plain_metric(gold, pred, trace=None): return score_and_feedback(gold, pred)[0]

if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "check":
        exs = load("corpus_cases")[:4]; prog = Profiler()
        for ex in exs:
            t = time.perf_counter(); pred = prog(statistics=ex.statistics); s, fb = score_and_feedback(ex, pred)
            print(f"{ex.name}: score {s:.2f} in {time.perf_counter()-t:.1f}s | {fb[:200]}")
    else:
        budget = sys.argv[2] if len(sys.argv) > 2 else "light"; out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(tempfile.mkdtemp(prefix="optimized-")); out.mkdir(parents=True, exist_ok=True)
        data = load("corpus_train"); random.Random(7).shuffle(data); dev, train = data[:40], data[40:]
        print(f"train {len(train)} dev {len(dev)} budget {budget}", flush=True)
        prog = Profiler()
        base = dspy.Evaluate(devset=dev, metric=plain_metric, num_threads=8, display_progress=False)(prog)
        print("seed instructions on dev:", base, flush=True)
        gepa = dspy.GEPA(metric=metric, auto=budget, reflection_lm=reflection_lm, num_threads=8, track_stats=True, reflection_minibatch_size=4)
        optimized = gepa.compile(prog, trainset=train, valset=dev)
        after = dspy.Evaluate(devset=dev, metric=plain_metric, num_threads=8, display_progress=False)(optimized)
        print("optimized instructions on dev:", after, flush=True)
        optimized.save(str(out / f"optimized-{budget}.json"))
        (out / f"instructions-{budget}.txt").write_text(optimized.predict.signature.instructions, encoding="utf-8")
        print("saved", out / f"instructions-{budget}.txt")
