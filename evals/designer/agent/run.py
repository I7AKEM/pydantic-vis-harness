"""Evaluate the designer against saved analyst reports; model access is opt-in through main."""

import argparse
import asyncio
import json
import os
import re
import shutil
from dataclasses import dataclass
from html import escape
from pathlib import Path

import duckdb
from dotenv import load_dotenv
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext, LLMJudge

from vis_agent.analyst.agent import ARABIC
from vis_agent.analyst.models import AnalysisReport
from vis_agent.designer.agent import (
    DEFAULT_DESIGNER_MODEL, build_prompt, create_designer, design_chart, render_design,
)
from vis_agent.designer.check import check_spec
from vis_agent.designer.models import DesignReport, SpecError
from vis_agent.designer.recommend import recommend_charts
from vis_agent.designer.syntax import parse
from vis_agent.models import DataBrief, Intent
from vis_agent.render.base import Rendered as RenderResult, RendererUnavailable, RenderFailed

from .corpus_tools.select import TASK_TO_INTENT
from .indicator.scoring import IndicatorExpectation, metric_fidelity, presentation_fit, rendered_fidelity

CASES_PATH = Path(__file__).with_name("cases.json")
RUBRIC = {"type": "The chart type fits the intent and the shape of the result.",
          "roles": "The right columns hold the right roles.",
          "title": "The title says what is shown, in the caller's language, and is true.",
          "units": "Units and number formats are right.",
          "honest": "Nothing misleads: zero baseline, sort, readable labels, emphasis on what was asked.",
          "explanation": "The explanation is honest and in the caller's language."}
INDICATOR_RUBRIC = "For indicators check primary metrics, scope, supporting values, NULL state, faithful scale, and unclipped text; axes are not applicable."

# Lists retain repeats; output identity connects each evaluation to its own render.
outputs: dict[str, list[DesignReport]] = {}
renders: dict[str, dict[int, Path]] = {}
render_results: dict[str, dict[int, RenderResult | str]] = {}


def _appropriate_deferral(ctx) -> bool:
    """Only an independently incomplete result may be sent back for analysis repair."""
    gold = ctx.expected_output.get("indicator")
    if gold and gold["mode"] == "incomplete":
        return presentation_fit(IndicatorExpectation.model_validate(gold),
                                ctx.output.design.chart if ctx.output.design else None,
                                ctx.output.clarification is not None, getattr(ctx.output, "revision", None))
    return ctx.expected_output["expect"] == "clarification" and ctx.output.clarification is not None


def _spec(ctx):
    if ctx.output.design is not None:
        try:
            return parse(ctx.output.design.spec)
        except SpecError:
            pass
    return None


@dataclass
class Delivered(Evaluator[dict, DesignReport, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, DesignReport, dict]) -> float:
        return float(_appropriate_deferral(ctx) or (
            ctx.expected_output["expect"] == "design" and ctx.output.design is not None
        ))


@dataclass
class Passed(Evaluator[dict, DesignReport, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, DesignReport, dict]) -> float:
        if ctx.output.design is None:
            return 1.0
        report = AnalysisReport.model_validate_json(Path(ctx.inputs["report"]).read_text(encoding="utf-8"))
        return float(check_spec(ctx.output.design.spec, report.analysis.columns, report.result,
                                intent=ctx.output.design.intent).ok)


@dataclass
class ChartAccepted(Evaluator[dict, DesignReport, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, DesignReport, dict]) -> float:
        if _appropriate_deferral(ctx):
            return 1.0
        if ctx.output.design is None:
            return 0.0
        charts = ctx.expected_output["charts"]
        if charts is None:
            report = AnalysisReport.model_validate_json(Path(ctx.inputs["report"]).read_text(encoding="utf-8"))
            charts = reference_charts(report, ctx.output.design.intent)
        return float(ctx.output.design.chart in charts)


def reference_charts(report: AnalysisReport, intent: Intent | None) -> list[str]:
    """Rules agreement for the declared intent, not a correctness label."""
    if report.analysis is None or report.result is None or not report.result.rows:
        return []
    candidates = recommend_charts(report.analysis.columns, report.result, intent=intent).candidates
    if not candidates:
        return []
    nearby = {c.name for c in candidates if c.score >= 0 and c.score >= candidates[0].score - 1}
    # A swap partner counts only when the rules listed it as a candidate with a non-negative score.
    for first, second in (("bar", "column"), ("grouped_bar", "grouped_column"),
                          ("stacked_bar", "stacked_column"), ("pie", "donut")):
        if nearby.intersection((first, second)):
            nearby.update((first, second))
    return [c.name for c in candidates if c.name in nearby and c.score >= 0]


@dataclass
class IntentPlausible(Evaluator[dict, DesignReport, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, DesignReport, dict]) -> float:
        intent = TASK_TO_INTENT.get((ctx.metadata or {}).get("task"))
        if intent is None:
            return 1.0
        return float(ctx.output.design is not None and ctx.output.design.intent == intent)


@dataclass
class LanguageRight(Evaluator[dict, DesignReport, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, DesignReport, dict]) -> float:
        spec = _spec(ctx)
        if spec is None:
            return float(_appropriate_deferral(ctx))
        language = ctx.expected_output["language"]
        title = spec.title or ""
        script_right = bool(ARABIC.search(title)) if language == "ar" else (
            bool(re.search(r"[A-Za-z]", title)) and not ARABIC.search(title)
        )
        return float(spec.language == language and script_right)


@dataclass
class BindingRight(Evaluator[dict, DesignReport, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, DesignReport, dict]) -> float:
        spec = _spec(ctx)
        if spec is None:
            return float(_appropriate_deferral(ctx))
        expected = ctx.expected_output
        return float(all(spec.bind.get(role) == column for role, column in expected["bind"].items()) and (
            expected["emphasis"] is None or expected["emphasis"] in spec.emphasis
        ))


@dataclass
class Metrics(Evaluator[dict, DesignReport, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, DesignReport, dict]) -> dict:
        return {"requests": ctx.output.requests, "check_calls": ctx.output.check_calls, "seconds": ctx.output.seconds}


@dataclass
class PresentationFit(Evaluator[dict, DesignReport, dict]):
    def evaluate(self, ctx) -> float:
        gold = IndicatorExpectation.model_validate(ctx.expected_output["indicator"])
        return float(presentation_fit(gold, ctx.output.design.chart if ctx.output.design else None,
                                      ctx.output.clarification is not None, getattr(ctx.output, "revision", None)))


@dataclass
class MetricFidelity(Evaluator[dict, DesignReport, dict]):
    def evaluate(self, ctx) -> float:
        gold = IndicatorExpectation.model_validate(ctx.expected_output["indicator"])
        if gold.mode == "incomplete":
            return float(_appropriate_deferral(ctx))
        report = AnalysisReport.model_validate_json(Path(ctx.inputs["report"]).read_text(encoding="utf-8"))
        return float(metric_fidelity(gold, _spec(ctx), report))


@dataclass
class Rendered(Evaluator[dict, DesignReport, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, DesignReport, dict]) -> float:
        if _appropriate_deferral(ctx):
            return 1.0
        result = render_results.get(ctx.inputs["name"], {}).get(id(ctx.output))
        chart = ctx.output.design.chart if ctx.output.design is not None else None
        if chart == "indicator":
            gold = ctx.expected_output.get("indicator")
            if not isinstance(result, RenderResult):
                return 0.0
            if gold is None:
                # Legacy suites retain a rendering smoke score, not an invented semantic gold.
                return float(result.png.is_file() and bool(result.texts) and bool(result.text_bounds))
            source = AnalysisReport.model_validate_json(Path(ctx.inputs["report"]).read_text(encoding="utf-8"))
            return float(rendered_fidelity(IndicatorExpectation.model_validate(gold), result, source))
        # Thin strokes cover under two percent of a line chart; measured 1.8 to 1.9 percent on real cases.
        blank = 0.01 if chart in {"line", "area", "scatter"} else 0.02
        return float(isinstance(result, RenderResult) and result.png.is_file() and (
            chart == "table" or result.non_background_share >= blank
        ))


# Cases whose analyst report holds no table cannot be designed; they are listed here, not scored.
unanswered: list[str] = []


def load_cases(cases_path=CASES_PATH, split: str | None = None) -> list[Case]:
    cases_path = Path(cases_path)
    cases = []
    unanswered.clear()
    for case in json.loads(cases_path.read_text(encoding="utf-8")):
        if split is not None and case.get("split") != split:
            continue
        focused = cases_path.parent.name == "indicator" or case.get("indicator") is not None
        if focused:
            if case.get("charts") is None or case.get("indicator") is None:
                raise ValueError(f"{case['name']}: focused indicator cases require independent charts and metric golds")
            IndicatorExpectation.model_validate(case["indicator"])
        path = (cases_path.parent / case["report"]).resolve()
        report = AnalysisReport.model_validate_json(path.read_text(encoding="utf-8"))
        if report.analysis is None or report.result is None:
            unanswered.append(case["name"])
            continue
        brief = DataBrief.model_validate(case["brief"]) if case["brief"] else None
        cases.append(Case(
            name=case["name"],
            inputs={"name": case["name"], "report": str(path), "brief": case["brief"],
                    "question": report.question, "result_description": build_prompt(report, brief).model_dump()},
            expected_output={**{key: case[key] for key in ("expect", "charts", "language", "bind", "emphasis")},
                             **({"indicator": case["indicator"]} if focused else {})},
            metadata={"why": case["why"], **(case.get("metadata") or {}),
                      **{key: case[key] for key in ("split", "seeded", "task") if key in case}},
        ))
    return cases


def build_dataset(cases_path=CASES_PATH, judge: str | None = None, split: str | None = None) -> Dataset:
    cases = load_cases(cases_path, split)
    evaluators = [Delivered(), Passed(), ChartAccepted(), LanguageRight(), BindingRight(), Metrics()]
    if any("indicator" in case.expected_output for case in cases):
        if not all("indicator" in case.expected_output for case in cases):
            raise ValueError("Do not mix focused indicator golds and legacy rules-agreement cases")
        evaluators.extend([PresentationFit(), MetricFidelity()])
    if any(case.expected_output["charts"] is None or "split" in case.metadata for case in cases):
        evaluators.append(IntentPlausible())
    if judge:
        evaluators.append(LLMJudge(
            rubric="\n".join(RUBRIC.values()) + "\nJudge the design against the question and the result description."
                   + ("\n" + INDICATOR_RUBRIC if any("indicator" in c.expected_output for c in cases) else ""),
            model=judge, include_input=True,
        ))
    return Dataset(name="designer-agent", cases=cases, evaluators=evaluators)


def make_task(designer, render_directory: Path | None = None):
    async def task(inputs: dict) -> DesignReport:
        report = AnalysisReport.model_validate_json(Path(inputs["report"]).read_text(encoding="utf-8"))
        brief = DataBrief.model_validate(inputs["brief"]) if inputs["brief"] else None
        output = await design_chart(report, designer, brief)
        name = inputs["name"]
        runs = outputs.setdefault(name, [])
        runs.append(output)
        if render_directory is not None and output.design is not None:
            directory = render_directory / name
            if len(runs) > 1:
                directory /= f"repeat-{len(runs)}"
            directory.mkdir(parents=True, exist_ok=True)
            renders.setdefault(name, {})[id(output)] = directory
            (directory / "spec.txt").write_text(output.design.spec, encoding="utf-8")
            (directory / "explanation.txt").write_text(output.design.explanation, encoding="utf-8")
            (directory / "chart.png").unlink(missing_ok=True)
            try:
                result = await asyncio.to_thread(render_design, report, output.design, directory)
            except (RendererUnavailable, RenderFailed, ValueError, OSError) as error:
                result = str(error)
            render_results.setdefault(name, {})[id(output)] = result
        return output

    return task


def write_review_page(directory: Path, entries: list[dict]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    sections = []
    split_order = {"train": 0, "dev": 1, "heldout": 2}
    previous_split = None
    for index, entry in enumerate(sorted(entries, key=lambda entry: split_order.get(entry.get("split"), 3))):
        text = lambda key: escape(str(entry.get(key) or ""))
        split = entry.get("split") or "unsplit"
        if split != previous_split:
            sections.append(f"<h2>Split: {escape(split)}</h2>")
            previous_split = split
        seeded = "true" if entry.get("seeded", False) else "false"
        badge = " · Seeded" if entry.get("seeded", False) else ""
        checks = "".join(f'<label><input type="checkbox" name="{key}"> {escape(label)}</label>'
                         for key, label in RUBRIC.items())
        picture = f'<img src="{text("image")}" alt="{text("chart")}">' if entry.get("image") else "<p>No image.</p>"
        sections.append(f'''<section data-name="{text('name')}" data-model="{text('model')}"
data-split="{text('split')}" data-seeded="{seeded}">
<h2>{text('name')}</h2><p dir="auto">{text('question')}</p>
<p>Language: {text('language')} · Chart: {text('chart')}{badge}</p>{picture}
<pre class="spec">{text('spec')}</pre><p dir="auto">{text('explanation')}</p>
<p>Compromises: {escape(json.dumps(entry.get('compromises', []), ensure_ascii=False))}</p>
<p>Automatic scores: {escape(json.dumps(entry.get('scores', {}), ensure_ascii=False))}</p>
<p>Independent expected metrics: {escape(json.dumps(entry.get('expected_indicator'), ensure_ascii=False))}</p>
<p>{text('error')}</p><fieldset><legend>Mark each failed criterion</legend>{checks}</fieldset>
<label><input type="radio" name="verdict-{index}" value="pass"> Pass</label>
<label><input type="radio" name="verdict-{index}" value="fail"> Fail</label>
<label>Note <textarea class="note"></textarea></label></section>''')
    page = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Designer review</title>
<style>body{font:16px system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#202124}
section{border-top:1px solid #bbb;margin-top:2rem;padding:1rem 0}img{max-width:100%;height:auto}
pre{white-space:pre-wrap;background:#f4f4f4;padding:1rem}label{display:block;margin:.5rem 0}
textarea{display:block;width:100%;min-height:5rem}button,input{font:inherit}#json{min-height:12rem}</style>
<h1>Designer review</h1><label>Your name <input id="reviewer" required></label>
<p>Judge all six criteria. Check the criteria that failed, choose a verdict, and add a note.</p>
<button id="copy">Copy judgments JSON</button><p id="message" role="status"></p>
<textarea id="json" aria-label="Judgments JSON" readonly></textarea>
''' + "\n".join(sections) + '''
<script>
document.getElementById('copy').addEventListener('click', async () => {
  const by = document.getElementById('reviewer').value.trim();
  const message = document.getElementById('message');
  if (!by) { message.textContent = 'Enter your name first.'; return; }
  const judgments = {};
  for (const section of document.querySelectorAll('section')) {
    const verdict = section.querySelector('input[type=radio]:checked');
    if (!verdict) continue;
    const failed = Array.from(section.querySelectorAll('input[type=checkbox]:checked'), box => box.name);
    if (verdict.value === 'pass' && failed.length) {
      message.textContent = 'A passing case cannot have failed criteria: ' + section.dataset.name;
      return;
    }
    judgments[section.dataset.name] = {
      verdict: verdict.value, failed, note: section.querySelector('.note').value, by,
      date: new Date().toISOString().slice(0, 10), model: section.dataset.model,
      split: section.dataset.split || null, seeded: section.dataset.seeded === 'true',
      spec: section.querySelector('.spec').textContent
    };
  }
  const text = JSON.stringify(judgments, null, 2);
  document.getElementById('json').value = text;
  try { await navigator.clipboard.writeText(text); message.textContent = 'Copied judgments JSON.'; }
  catch { message.textContent = 'Clipboard unavailable. Copy the JSON from the text area.'; }
});
</script></html>'''
    path = directory / "index.html"
    path.write_text(page, encoding="utf-8")
    return path


def judgment_summary(judgments: dict) -> dict:
    judged = [entry for entry in judgments.values() if entry.get("verdict") in {"pass", "fail"}]
    with duckdb.connect() as connection:
        connection.execute("""
            CREATE TABLE judgments AS
            SELECT key AS id, value->'failed' AS failed,
                   (value->>'verdict') = 'pass'
                       AND coalesce(json_array_length(value->'failed'), 0) = 0 AS correct,
                   coalesce((value->>'seeded')::BOOLEAN, false) AS seeded
            FROM json_each(?)
        """, [json.dumps(judged)])

        def totals(seeded: bool | None = None) -> dict:
            row = connection.execute("""
                SELECT count(*), count(*) FILTER (WHERE correct), coalesce(avg(correct::INT), 0)
                FROM judgments WHERE ? IS NULL OR seeded = ?
            """, [seeded, seeded]).fetchone()
            return dict(zip(("judged", "correct", "share"), row))

        summary = totals()
        summary["failed_by_criterion"] = dict(connection.execute("""
            SELECT criterion, count(DISTINCT id) FROM (
                SELECT j.id, f.value->>'$' AS criterion
                FROM judgments j, json_each(j.failed) f
            ) GROUP BY criterion ORDER BY criterion
        """).fetchall())
        # Keep the legacy summary's exact shape for judgments without provenance.
        if any("seeded" in entry for entry in judged):
            summary.update(seeded=totals(True), unseeded=totals(False))
        return summary


def saved_spec_summary(cases_path: Path, judgments: dict, split: str | None = None) -> dict:
    cases = {case.name: case for case in load_cases(cases_path, split)}
    checks = []
    for name, judgment in judgments.items():
        case = cases.get(re.sub(r" \[\d+/\d+\]$", "", name))
        if case is None or not judgment.get("spec") or judgment.get("verdict") not in {"pass", "fail"}:
            continue
        report = AnalysisReport.model_validate_json(Path(case.inputs["report"]).read_text(encoding="utf-8"))
        checks.append(check_spec(judgment["spec"], report.analysis.columns, report.result).ok)
    return {"delivered_specs": len(checks), "passed": sum(checks),
            "share": sum(checks) / len(checks) if checks else None}


def _review_entries(report, model: str, directory: Path) -> list[dict]:
    entries = []
    for case in report.cases:
        output = case.output
        name = case.inputs["name"]
        design = output.design
        result = render_results.get(name, {}).get(id(output))
        folder = renders.get(name, {}).get(id(output))
        entries.append({
            "name": case.name, "question": output.question, "language": case.expected_output["language"],
            "chart": design.chart if design else None, "spec": design.spec if design else "",
            "explanation": design.explanation if design else (
                output.clarification.question if output.clarification else (
                    "\n".join((output.revision.problem, output.revision.requested_change, output.revision.preserve))
                    if output.revision else "\n".join(output.warnings))),
            "image": str((folder / "chart.png").relative_to(directory)) if isinstance(result, RenderResult) else None,
            "compromises": [item.model_dump() for item in (
                result.compromises if isinstance(result, RenderResult) else design.compromises if design else [])],
            "scores": {key: value.value for key, value in {**case.scores, **case.assertions}.items()},
            "model": model, "error": result if isinstance(result, str) else None,
            "split": (case.metadata or {}).get("split"),
            "seeded": (case.metadata or {}).get("seeded", False),
            "expected_indicator": case.expected_output.get("indicator"),
            "observed_outcome": "clarification" if output.clarification else (
                "analysis_revision" if output.revision else design.chart if design else "failed"),
            "analysis_revision": output.revision.model_dump(mode="json") if output.revision else None,
            "family": (case.metadata or {}).get("family"),
            "pair": (case.metadata or {}).get("pair"),
            "source_report": case.inputs["report"],
        })
    return entries


def judge_agreement(report, judgments: dict, model: str) -> dict:
    matches = []
    for case in report.cases:
        human = judgments.get(case.name)
        assertion = case.assertions.get("LLMJudge")
        spec = case.output.design.spec if case.output.design else ""
        if (human and human.get("verdict") in {"pass", "fail"} and assertion is not None
                and human.get("spec") == spec and human.get("model") == model):
            verdict = human["verdict"] == "pass" and not human.get("failed")
            matches.append(assertion.value == verdict)
    return {"compared": len(matches), "agreement": sum(matches) / len(matches) if matches else None}


def paired_summary(entries: list[dict]) -> list[dict]:
    """Score counterfactual relationships, keeping repeated runs within their source family."""
    groups = {}
    for entry in entries:
        if entry.get("pair"):
            groups.setdefault(entry["pair"], []).append(entry)
    results = []
    for family, members in groups.items():
        ok = all(entry["scores"].get("PresentationFit") == 1 and entry["scores"].get("MetricFidelity") == 1
                 for entry in members)
        bindings = []
        for entry in members:
            gold = entry["expected_indicator"]
            wanted = {c["value"] for c in gold["cards"]}
            try:
                parsed = parse(entry["spec"]) if entry.get("spec") else None
                actual = {c.value for c in parsed.cards} if parsed and parsed.type == "indicator" else set()
            except SpecError:
                actual = set()
                ok = False
            bindings.append((wanted, actual, gold["mode"]))
        for left_index, (wanted, actual, mode) in enumerate(bindings):
            for other_wanted, other_actual, other_mode in bindings[left_index + 1:]:
                if mode in {"required", "unavailable"} and other_mode in {"required", "unavailable"}:
                    # A permutation keeps primary identity; a count/share question changes it.
                    ok = ok and ((wanted == other_wanted) == (actual == other_actual))
                if {mode, other_mode} == {"required", "forbidden"}:
                    ok = ok and bool(actual) != bool(other_actual)
        results.append({"family": family, "observations": len(members), "passed": ok})
    return results


def _print_case_counts(cases: list[Case]) -> None:
    with duckdb.connect() as connection:
        total, seeded, unseeded = connection.execute("""
            SELECT count(*), count(*) FILTER (WHERE value::BOOLEAN),
                   count(*) FILTER (WHERE NOT value::BOOLEAN)
            FROM json_each(?)
        """, [json.dumps([bool(case.metadata.get("seeded", False)) for case in cases])]).fetchone()
    print(f"cases: {total}; seeded: {seeded}; unseeded: {unseeded}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--split", choices=("train", "dev", "heldout", "discovery", "confirmation"))
    parser.add_argument("--model")
    parser.add_argument("--max-concurrency", type=int, default=4)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--judge", metavar="MODEL")
    parser.add_argument("--judgments", action="store_true")
    parser.add_argument("--mismatches", action="store_true")
    parser.add_argument("--out", type=Path, help="Save portable scores, specs, reports, and run provenance.")
    args = parser.parse_args()
    judgments_path = args.cases.with_name("judgments.json")
    judgments = json.loads(judgments_path.read_text(encoding="utf-8"))["judgments"] if judgments_path.exists() else {}
    if args.judgments:
        cases = {case.name: case for case in load_cases(args.cases, args.split)}
        selected = {}
        for name, judgment in judgments.items():
            case = cases.get(re.sub(r" \[\d+/\d+\]$", "", name))
            if args.split is not None and case is None:
                continue
            metadata = {key: case.metadata[key] for key in ("split", "seeded") if key in case.metadata} if case else {}
            selected[name] = {**judgment, **metadata}
        judgments = selected
        _print_case_counts(list(cases.values()))
        print(json.dumps(judgment_summary(judgments), ensure_ascii=False, indent=2))
        print("saved spec checks: " + json.dumps(saved_spec_summary(args.cases, judgments, args.split)))
        return
    load_dotenv()
    model = args.model or os.getenv("PYDANTIC_AI_DESIGNER_MODEL") or DEFAULT_DESIGNER_MODEL
    if args.judge and args.judge.removeprefix("openrouter:") == model.removeprefix("openrouter:"):
        parser.error("--judge must name a model other than the designer's")
    designer = create_designer(model)
    dataset = build_dataset(args.cases, args.judge, args.split)
    directory = args.cases.parent / "renders" / (re.sub(r"[^A-Za-z0-9_.-]+", "-", model).strip(".-") or "model")
    if args.split:
        directory /= args.split
    outputs.clear()
    renders.clear()
    render_results.clear()
    if args.render:
        dataset.add_evaluator(Rendered())
    report = asyncio.run(dataset.evaluate(make_task(designer, directory if args.render else None),
                                         max_concurrency=args.max_concurrency, repeat=args.repeat))
    if args.out:
        from evals.evidence import provenance
        args.out.parent.mkdir(parents=True, exist_ok=True)
        entries = _review_entries(report, model, directory)
        if args.render:
            portable = args.out.parent / (args.out.stem + "-assets")
            shutil.copytree(directory, portable, dirs_exist_ok=True)
            for entry in entries:
                if entry["image"]:
                    entry["image"] = str(Path(portable.name) / entry["image"])
        args.out.write_text(json.dumps({"provenance": provenance(args.cases, {"designer": model}, args.repeat),
                                       "cases": entries, "paired_scores": paired_summary(entries),
                                       "inputs": {case.name: json.loads(Path(case.inputs["report"]).read_text())
                                                  for case in dataset.cases},
                                       "outputs": {name: [o.model_dump(mode="json") for o in runs]
                                                   for name, runs in outputs.items()}}, ensure_ascii=False, indent=2), encoding="utf-8")
    report.print(include_input=False, include_output=False)
    print(f"model: {model}")
    if unanswered:
        print(f"unanswered by the analyst, excluded from the scores: {len(unanswered)} ({', '.join(unanswered)})")
    _print_case_counts(dataset.cases)
    if args.render:
        print(f"review page: {write_review_page(directory, _review_entries(report, model, directory))}")
    if args.mismatches:
        for case in report.cases:
            failed = [key for key in ("ChartAccepted", "LanguageRight", "BindingRight", "IntentPlausible")
                      if key in case.scores and case.scores[key].value < 1]
            if failed:
                print(f"{case.name}: {', '.join(failed)}\n{case.output.design.spec if case.output.design else '(no spec)'}")
    if args.judge and judgments:
        print("judge agreement: " + json.dumps(judge_agreement(report, judgments, model)))


if __name__ == "__main__":
    main()
