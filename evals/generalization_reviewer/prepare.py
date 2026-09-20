"""Render new, synthetic paired inspection probes. No model calls or pixel editing."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from vis_agent.analyst.models import Analysis, AnalysisReport, QueryResult, ResultColumn
from vis_agent.designer.agent import render_design
from vis_agent.designer.models import Design, IndicatorCard, Spec
from vis_agent.designer.syntax import to_text
from vis_agent.models import DataBrief


HERE = Path(__file__).resolve().parent
STAMP = datetime(2026, 9, 17, tzinfo=timezone.utc)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def column(name, meaning, kind="measure", unit=None):
    return ResultColumn(name=name, meaning=meaning, kind=kind, unit=unit, source=name)


def report(key, question, columns, rows):
    return AnalysisReport(
        dataset_id=f"synthetic_{key}", question=question, language="English",
        analysis=Analysis(sql="SELECT supplied_columns FROM synthetic_fixture", columns=columns,
                          summary="Supplied synthetic measurements.", assumptions=[]),
        result=QueryResult(sql="SELECT supplied_columns FROM synthetic_fixture",
                           columns=[c.name for c in columns], rows=rows, row_count=len(rows),
                           types=["VARCHAR" if c.kind == "category" else "DOUBLE" for c in columns], seconds=0),
        seconds=0, created_at=STAMP,
    )


def design(spec: Spec) -> Design:
    return Design(spec=to_text(spec), chart=spec.type, intent=None, explanation="Direct presentation of the supplied values.",
                  considered=[spec.type], compromises=[])


def with_rows(source: AnalysisReport, rows) -> AnalysisReport:
    changed = source.model_copy(deep=True)
    changed.result.rows = rows
    changed.result.row_count = len(rows)
    return changed


def pairs():
    common = {"width": 960, "height": 640, "language": "en", "sort": "none"}

    source = report("nozzle_readings", "Compare flow by nozzle; preserve the supplied nozzle/value pairings.", [
        column("nozzle", "Nozzle", "category"), column("flow", "Flow", unit="L/min"),
    ], [["Nozzle A", 9], ["Nozzle B", 17], ["Nozzle C", 26]])
    spec = Spec(type="bar", title="Nozzle flow", description="Flow by nozzle", bind={"category": "nozzle", "value": "flow"},
                axis_x_title="Flow (L/min)", axis_y_title="Nozzle", labels="on", **common)
    yield "bar_pairing", source, spec, with_rows(source, [["Nozzle A", 26], ["Nozzle B", 17], ["Nozzle C", 9]]), spec, (
        "Nozzle A must show 9 and Nozzle C 26; the defective image swaps their values to 26 and 9."
    )

    source = report("pressure_runs", "Show pressure over the four runs in kPa; no unit conversion is requested.", [
        column("run", "Run", "category"), column("pressure", "Pressure", unit="kPa"),
    ], [["Run 1", 120], ["Run 2", 180], ["Run 3", 150], ["Run 4", 210]])
    spec = Spec(type="line", title="Pressure by run", description="Pressure in kPa", bind={"time": "run", "value": "pressure"},
                axis_x_title="Run", axis_y_title="Pressure (kPa)", labels="on", **common)
    bad = spec.model_copy(update={"axis_y_title": "Pressure (psi)"})
    yield "line_unit", source, spec, source, bad, "The defective Y axis says psi while the supplied values and required title are kPa."

    source = report("coating_trials", "Compare Aster and Beryl coating strength by trial; retain the literal series labels.", [
        column("trial", "Trial", "category"), column("coating", "Coating", "category"),
        column("strength", "Strength", unit="MPa"),
    ], [["Trial 1", "Aster", 5], ["Trial 1", "Beryl", 16], ["Trial 2", "Aster", 8], ["Trial 2", "Beryl", 22]])
    spec = Spec(type="grouped_bar", title="Coating strength", description="Coatings within each trial",
                bind={"category": "trial", "group": "coating", "value": "strength"},
                axis_x_title="Strength (MPa)", axis_y_title="Trial", labels="on", legend="on", **common)
    bad = spec.model_copy(update={"value_labels": {"coating": {"Aster": "Beryl", "Beryl": "Aster"}}})
    yield "grouped_legend", source, spec, source, bad, (
        "The defective legend relabels Aster's short 5/8 bars as Beryl and Beryl's long 16/22 bars as Aster."
    )

    source = report("alloy_samples", "Show all four supplied alloy sample readings as an exact table.", [
        column("sample", "Alloy sample", "category"), column("reading", "Conductance", unit="mS"),
    ], [["Amber", 0.42], ["Cobalt", 0.86], ["Dune", 0.58], ["Ember", 0.74]])
    spec = Spec(type="table", title="Alloy sample readings", description="All four supplied samples",
                column_labels={"sample": "Alloy sample", "reading": "Conductance (mS)"},
                width=960, height=640, language="en")
    yield "table_missing_row", source, spec, with_rows(source, [source.result.rows[i] for i in [0, 2, 3]]), spec, (
        "The defective table omits the entire Cobalt row (0.86 mS), one of four required supplied rows."
    )

    source = report("energy_batch", "Show the energy consumed by Batch Z, exactly as supplied in kWh.", [
        column("batch", "Batch", "category"), column("energy", "Energy consumed", unit="kWh"),
    ], [["Batch Z", 88]])
    spec = Spec(type="indicator", title="Energy consumed", description="Supplied batch energy",
                cards=[IndicatorCard(value="energy", context=["batch"])], width=960, height=480, language="en")
    yield "indicator_value", source, spec, with_rows(source, [["Batch Z", 880]]), spec, (
        "The defective headline shows 880 kWh although the supplied energy value is 88 kWh."
    )

    source = report("detector_response", "Plot injection volume on X and detector peak area on Y using the supplied bindings.", [
        column("volume", "Injection volume", unit="mL"), column("peak_area", "Peak area", unit="mAU*s"),
    ], [[1, 9], [2, 16], [4, 35], [8, 65]])
    spec = Spec(type="scatter", title="Detector response", description="Peak area against injection volume",
                bind={"x": "volume", "y": "peak_area"}, axis_x_title="Injection volume (mL)",
                axis_y_title="Peak area (mAU*s)", **common)
    bad = spec.model_copy(update={"bind": {"x": "peak_area", "y": "volume"}})
    yield "scatter_binding", source, spec, source, bad, (
        "The defective plot places peak areas 9/16/35/65 on the X axis labelled volume and volumes 1/2/4/8 on Y."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "fixtures")
    args = parser.parse_args()
    root = args.output.resolve()
    if (root / "manifest.json").exists():
        raise SystemExit("Refusing to overwrite a prepared probe manifest. Use a new output directory.")
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    for family, reference, expected_spec, bad_report, bad_spec, defect in pairs():
        expected = design(expected_spec)
        brief = DataBrief(raw_question=reference.question, caveats=["Synthetic prepared values; preserve their exact meanings and units."])
        for variant, actual_report, actual_spec in [("clean", reference, expected_spec), ("defect", bad_report, bad_spec)]:
            key = f"{family}_{variant}"
            target = root / key
            rendered = render_design(actual_report, design(actual_spec), target)
            payload = {
                "id": key, "family": family, "proposed_label": "pass" if variant == "clean" else "revise",
                "construction": "Faithful rendering of the reference." if variant == "clean" else defect,
                "reference": {"report": reference.model_dump(mode="json"), "design": expected.model_dump(mode="json"),
                              "brief": brief.model_dump(mode="json")},
                "render_input": {"report": actual_report.model_dump(mode="json"), "spec": design(actual_spec).spec},
                "render": rendered.model_dump(mode="json"),
            }
            write_json(target / "case.json", payload)
            entries.append({"id": key, "family": family, "proposed_label": payload["proposed_label"],
                            "case": f"{key}/case.json", "case_sha256": digest(target / "case.json"),
                            "image": f"{key}/chart.png", "image_sha256": digest(target / "chart.png")})
            print(key, rendered.width, rendered.height, flush=True)
    renderer = Path(__file__).resolve().parents[2] / "vis_agent" / "render" / "gptvis"
    manifest = {
        "schema_version": 1, "purpose": "Synthetic reviewer capability probe; not human gold or a replacement for the labelled production set.",
        "label_policy": "Proposed labels are excluded until independently inspected in audit.json before any model calls.",
        "renderer_hashes": {name: digest(renderer / name) for name in ["render.mjs", "package-lock.json"]},
        "cases": entries,
    }
    write_json(root / "manifest.json", manifest)
    write_json(root / "audit.json", {"manifest_sha256": digest(root / "manifest.json"), "model_calls_started": False,
                                     "label_source": "Synthetic construction plus agent visual inspection; not human gold.",
                                     "cases": {entry["id"]: {"eligible": False, "reason": "Pending pre-model visual inspection."}
                                               for entry in entries}})
    print("manifest_sha256", digest(root / "manifest.json"), flush=True)


if __name__ == "__main__":
    main()
