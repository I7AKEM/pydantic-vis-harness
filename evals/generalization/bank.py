"""Author a synthetic intent/representation bank, never production prompt examples.

Freeze before running either arm. The content is deliberately independent of the
development CSV bank. No semantic population-generalization claim is implied.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSION = "transfer24-v1"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha256(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def csv_text(columns: list[str], rows: list[list]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return stream.getvalue()


def _families() -> list[dict]:
    # These are authored inputs, not selected failures or mutated development rows.
    return [
        {
            "id": "relationship_sequence", "taxonomy": "Same observations: association versus temporal path",
            "columns": ["date", "inlet_c", "pressure_kpa"],
            "rows": [["2026-02-01", 18, 101], ["2026-02-02", 24, 104], ["2026-02-03", 21, 109],
                     ["2026-02-04", 27, 105], ["2026-02-05", 20, 99], ["2026-02-06", 25, 112]],
            "descriptions": {"date": "Observation date; chronological order is meaningful",
                             "inlet_c": "Measured inlet temperature", "pressure_kpa": "Measured pressure"},
            "units": {"inlet_c": "°C", "pressure_kpa": "kPa"},
            "goals": [
                {"id": "association", "intent": "relation",
                 "request": "Show the association between inlet temperature (horizontal axis) and pressure (vertical axis). Each supplied observation must remain a separate point; do not connect points in time or claim causation.",
                 "charts": ["scatter"], "visible": ["inlet_c", "pressure_kpa"],
                 "bindings": {"x": "inlet_c", "y": "pressure_kpa"}, "measures": ["inlet_c", "pressure_kpa"]},
                {"id": "trajectory", "intent": "trend",
                 "request": "Show how pressure evolves through the observation dates in chronological order. Temperature is context, not a second axis. Use a graphical time series, not a table or a temperature-pressure scatterplot.",
                 "charts": ["line", "area", "column"], "visible": ["date", "pressure_kpa"],
                 "bindings": {}, "measures": ["pressure_kpa"], "forbid_measures": ["inlet_c"]},
            ],
        },
        {
            "id": "composition_independent_rates", "taxonomy": "Additive allocation versus non-additive per-group rates",
            "columns": ["channel", "allocated_hours", "failure_percent"],
            "rows": [["Inspection", 240, 6.5], ["Packaging", 160, 12.0], ["Dispatch", 360, 3.5], ["Rework", 40, 25.0]],
            "descriptions": {"channel": "Separate process activity", "allocated_hours": "Mutually exclusive allocated work hours; rows partition the full allocation",
                             "failure_percent": "Failures as a percent within each activity; denominators differ, so these percentages are not parts of a common whole"},
            "units": {"allocated_hours": "hours", "failure_percent": "%"},
            "goals": [
                {"id": "allocation", "intent": "composition",
                 "request": "Visualize how the complete work-hour allocation is divided among activities. Encode the supplied hours directly; do not substitute the failure rates or calculate a new percentage column.",
                 "charts": ["pie", "donut", "treemap", "bar", "column"], "visible": ["channel", "allocated_hours"],
                 "bindings": {"category": "channel", "value": "allocated_hours"}, "measures": ["allocated_hours"], "forbid_measures": ["failure_percent"]},
                {"id": "failure_comparison", "intent": "compare",
                 "request": "Compare the activity-specific failure percentages with an aligned baseline. These independent percentages are already expressed in percent units, not fractions and not shares of a common total. Show these rates, not allocated hours.",
                 "charts": ["bar", "column"], "visible": ["channel", "failure_percent"],
                 "bindings": {"category": "channel", "value": "failure_percent"}, "measures": ["failure_percent"], "forbid_measures": ["allocated_hours"]},
            ],
        },
        {
            "id": "nested_allocation", "taxonomy": "Within-parent composition versus aligned subgroup comparison",
            "columns": ["assembly", "module", "power_w"],
            "rows": [["Rig A", "Compute", 35], ["Rig A", "Cooling", 15], ["Rig A", "Storage", 10],
                     ["Rig B", "Compute", 20], ["Rig B", "Cooling", 30], ["Rig B", "Storage", 5],
                     ["Rig C", "Compute", 25], ["Rig C", "Cooling", 10], ["Rig C", "Storage", 20]],
            "descriptions": {"assembly": "Parent rig", "module": "Repeated module category within every parent rig",
                             "power_w": "Module power draw; modules partition their parent rig's draw"},
            "units": {"power_w": "W"},
            "goals": [
                {"id": "parent_composition", "intent": "composition",
                 "request": "Show each rig as one total-length mark subdivided by its modules, preserving the module power readings. Use absolute watts, not normalized percentages; do not merge identically named modules across rigs.",
                 "charts": ["stacked_bar", "stacked_column"], "visible": ["assembly", "module", "power_w"],
                 "bindings": {"category": "assembly", "group": "module", "value": "power_w"}, "measures": ["power_w"]},
                {"id": "module_comparison", "intent": "compare",
                 "request": "Make module-to-module power comparisons across rigs easy: each module reading needs its own aligned-baseline mark, with rig identity distinguishable. Do not stack the readings or sum them.",
                 "charts": ["grouped_bar", "grouped_column"], "visible": ["assembly", "module", "power_w"],
                 "bindings": {"value": "power_w"}, "measures": ["power_w"]},
            ],
        },
        {
            "id": "repeated_measurement_views", "taxonomy": "Repeated trajectories versus group-wise sample distributions",
            "columns": ["batch", "elapsed_min", "strength_mpa"],
            "rows": [["Mix Cedar", 0, 5], ["Mix Cedar", 10, 9], ["Mix Cedar", 20, 15], ["Mix Cedar", 30, 16], ["Mix Cedar", 40, 25],
                     ["Mix Birch", 0, 8], ["Mix Birch", 10, 11], ["Mix Birch", 20, 10], ["Mix Birch", 30, 19], ["Mix Birch", 40, 21],
                     ["Mix Maple", 0, 3], ["Mix Maple", 10, 13], ["Mix Maple", 20, 18], ["Mix Maple", 30, 22], ["Mix Maple", 40, 24]],
            "descriptions": {"batch": "Mixture batch", "elapsed_min": "Elapsed curing time in minutes; ordered measurement coordinate",
                             "strength_mpa": "Observed material strength; every row is a separate supplied observation"},
            "units": {"elapsed_min": "min", "strength_mpa": "MPa"},
            "goals": [
                {"id": "curing_paths", "intent": "trend",
                 "request": "Compare each mixture's strength trajectory over elapsed curing time. Preserve batch identity and the ordering of time within each trajectory. No averaging or fitted prediction.",
                 "charts": ["multi_line", "grouped_column"], "visible": ["batch", "elapsed_min", "strength_mpa"],
                 "bindings": {"group": "batch", "value": "strength_mpa"}, "measures": ["strength_mpa"]},
                {"id": "sample_spreads", "intent": "distribution",
                 "request": "Compare the distributions of the supplied strength observations within the three mixture batches, using the renderer's distribution display. Time ordering is irrelevant for this view. Do not average the source CSV or invent new measurements.",
                 "charts": ["boxplot"], "visible": ["batch", "strength_mpa"],
                 "bindings": {"category": "batch", "value": "strength_mpa"}, "measures": ["strength_mpa"]},
            ],
        },
        {
            "id": "mixed_unit_summary", "taxonomy": "Multimetric overview versus complete exact record presentation",
            "columns": ["window", "completed_jobs", "p95_delay_ms", "utilization_percent", "energy_kwh"],
            "rows": [["Evening trial", 840, 185, 73.5, 12.6]],
            "descriptions": {"window": "Authoritative trial label", "completed_jobs": "Number of completed jobs",
                             "p95_delay_ms": "Already computed 95th-percentile delay; do not recompute",
                             "utilization_percent": "Utilization already expressed as percent", "energy_kwh": "Measured energy use"},
            "units": {"completed_jobs": "jobs", "p95_delay_ms": "ms", "utilization_percent": "%", "energy_kwh": "kWh"},
            "goals": [
                {"id": "overview", "intent": "summary",
                 "request": "Create an at-a-glance overview of all four supplied trial metrics, retaining each metric's own unit and the trial label. They have different dimensions, so do not put them on a shared quantitative axis or invent a total.",
                 "charts": ["indicator", "table"], "visible": ["window", "completed_jobs", "p95_delay_ms", "utilization_percent", "energy_kwh"],
                 "bindings": {}, "measures": ["completed_jobs", "p95_delay_ms", "utilization_percent", "energy_kwh"]},
                {"id": "exact_record", "intent": "summary",
                 "request": "Produce an exact audit record: show the complete supplied row with all column labels and units together, without abbreviation, unit conversion or re-computation. A clearly labelled table is appropriate; independent metric cards are also acceptable only if every field remains visible.",
                 "charts": ["table", "indicator"], "visible": ["window", "completed_jobs", "p95_delay_ms", "utilization_percent", "energy_kwh"],
                 "bindings": {}, "measures": ["completed_jobs", "p95_delay_ms", "utilization_percent", "energy_kwh"]},
            ],
        },
        {
            "id": "opaque_metric_choice", "taxonomy": "Goal-sensitive metric selection with opaque literal identities",
            "columns": ["unit_id", "peak_kw", "wh_per_transaction"],
            "rows": [["0017", 4.2, 2.8], ["0402", 2.5, 4.0], ["0091", 3.8, 1.9], ["0700", 1.7, 3.4], ["0026", 5.1, 2.1]],
            "descriptions": {"unit_id": "Opaque literal equipment identifier; leading zeros are meaningful and no expansion or translated name exists",
                             "peak_kw": "Peak electrical demand", "wh_per_transaction": "Energy consumed per completed transaction; lower is more efficient"},
            "units": {"peak_kw": "kW", "wh_per_transaction": "Wh/transaction"},
            "literal_columns": ["unit_id"],
            "goals": [
                {"id": "demand_rank", "intent": "rank",
                 "request": "Rank the equipment by peak demand, highest first, using a clear graphical comparison. Keep every opaque identifier exactly as supplied, including leading zeros. The per-transaction efficiency metric is not the quantity to rank.",
                 "charts": ["bar", "column"], "visible": ["unit_id", "peak_kw"], "bindings": {"category": "unit_id", "value": "peak_kw"},
                 "measures": ["peak_kw"], "forbid_measures": ["wh_per_transaction"], "sort": "value desc"},
                {"id": "efficiency_rank", "intent": "rank",
                 "request": "Rank the equipment by energy efficiency: lowest energy per transaction first. Show the supplied Wh/transaction measurement, not its reciprocal and not peak demand. Keep every opaque identifier literally, including leading zeros.",
                 "charts": ["bar", "column"], "visible": ["unit_id", "wh_per_transaction"], "bindings": {"category": "unit_id", "value": "wh_per_transaction"},
                 "measures": ["wh_per_transaction"], "forbid_measures": ["peak_kw"], "sort": "value asc"},
            ],
        },
    ]


def make_bank() -> dict:
    cases, pairs, families = [], [], []
    for number, family in enumerate(_families(), 1):
        fid = family["id"]
        families.append({"id": fid, "taxonomy": family["taxonomy"], "split": "blinded_challenge",
                         "authoring_source": "independent synthetic task construction"})
        goal_originals = []
        for goal in family["goals"]:
            members = []
            for variant in ("original", "transformed"):
                original = variant == "original"
                # Column IDs are deliberately uninformative in the transformed
                # input. Meanings remain explicit in the authoritative brief.
                mapping = {name: name if original else f"field_{number}_{index + 1}"
                           for index, name in enumerate(family["columns"])}
                order = list(range(len(family["columns"]))) if original else list(reversed(range(len(family["columns"]))))
                columns = [mapping[family["columns"][index]] for index in order]
                row_order = list(range(len(family["rows"])))
                if not original:
                    row_order = row_order[1::2] + row_order[::2]
                rows = [[family["rows"][row][index] for index in order] for row in row_order]
                case_id = f"g{number:02d}-{goal['id']}-{variant}"
                members.append(case_id)
                if original:
                    goal_originals.append(case_id)
                request = goal["request"] + " Use English labels. The attached CSV is authoritative and already prepared. Present it without source research, new calculations, sampling, or aggregation. Return a usable rendered artifact."
                if not original:
                    request += " Column identifiers are arbitrary; use their supplied definitions rather than guessing from names."
                brief = {"source": "independently authored synthetic challenge data", "producer_agent": "data-agent",
                         "raw_question": request, "enriched_question": request, "intent": goal["intent"],
                         "column_descriptions": {mapping[k]: v for k, v in family["descriptions"].items()},
                         "units": {mapping[k]: v for k, v in family["units"].items()},
                         "caveats": ["Measurements and units are authoritative. No inference of missing observations, category meanings, or unrequested transformations."]}
                contract = {"allowed_charts": goal["charts"], "required_visible_columns": [mapping[x] for x in goal["visible"]],
                            "required_bindings": {k: mapping[v] for k, v in goal["bindings"].items()},
                            "primary_measures": [mapping[x] for x in goal["measures"]],
                            "forbidden_measures": [mapping[x] for x in goal.get("forbid_measures", [])],
                            "units": brief["units"], "literal_columns": [mapping[x] for x in family.get("literal_columns", [])],
                            "sort": goal.get("sort"), "no_source_rewrite": True,
                            "visual_rubric": ["Every encoded observation retains its source value and identity.",
                                              "Displayed units and scale match the bound measure; no invented mappings or claims.",
                                              "Required labels/marks are interpretable at the published display size.",
                                              "The stated goal is met; reasonable stylistic alternatives are not defects."],
                            "human_gold": False}
                content = csv_text(columns, rows)
                cases.append({"id": case_id, "family": fid, "goal": goal["id"], "variant": variant,
                              "split": "blinded_challenge", "filename": f"{case_id}.csv", "csv_text": content,
                              "source_csv_sha256": hashlib.sha256(content.encode()).hexdigest(), "brief": brief,
                              "request": request, "contract": contract, "source_columns": columns, "source_rows": rows,
                              "canonical_columns": {new: old for old, new in mapping.items()},
                              "provenance": {"synthetic": True, "derived_from_old50": False, "tuning_allowed": False}})
            pairs.append({"id": f"g{number:02d}-{goal['id']}-meaning-preserving", "kind": "meaning_preserving",
                          "family": fid, "members": members,
                          "transformations": ["column identifiers renamed with explicit semantic definitions", "column order permuted", "row order permuted"],
                          "assertion": "Equivalent canonical source observations and goal-appropriate visible bindings; neither identical chart type nor pixels required."})
        pairs.append({"id": f"g{number:02d}-goal-contrast", "kind": "goal_contrast", "family": fid, "members": goal_originals,
                      "assertion": "Same source, different intent contract; a different chart type is required only when the intent demands it."})
    return {"version": VERSION, "families": families, "cases": cases, "pairs": pairs,
            "provenance": {"author": "independent evaluation subagent", "human_gold": False,
                           "old50_cases_or_production_prompts_read_for_authoring": False,
                           "family_split_policy": "All six authored families are evaluation-only; none may be used for candidate tuning.",
                           "disjointness_limit": "Assets and task authoring are independent. Abstract capability overlap with prior corpora is not excluded; this is not proof of population generalization.",
                           "hidden_until_runtime_freeze": True}}


def freeze(directory: Path = HERE) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    bank_path, manifest_path = directory / "bank.json", directory / "freeze.json"
    if bank_path.exists() or manifest_path.exists():
        raise FileExistsError("Frozen bank exists; author a new version instead of replacing evaluation inputs.")
    bank = make_bank()
    payload = json.dumps(bank, ensure_ascii=False, indent=2) + "\n"
    bank_path.write_text(payload, encoding="utf-8")
    manifest = {"version": VERSION, "frozen_at": datetime.now(timezone.utc).isoformat(),
                "bank_sha256": hashlib.sha256(payload.encode()).hexdigest(), "semantic_sha256": sha256(bank),
                "authoring_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "case_count": len(bank["cases"]), "family_count": len(bank["families"]),
                "pair_count": len(bank["pairs"]), "tuning_allowed": False}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def load_bank(directory: Path = HERE) -> tuple[dict, dict]:
    content = (directory / "bank.json").read_bytes()
    manifest = json.loads((directory / "freeze.json").read_text())
    if hashlib.sha256(content).hexdigest() != manifest["bank_sha256"]:
        raise ValueError("Frozen evaluation bank hash mismatch")
    bank = json.loads(content)
    if sha256(bank) != manifest["semantic_sha256"]:
        raise ValueError("Frozen evaluation semantics hash mismatch")
    for case in bank["cases"]:
        if hashlib.sha256(case["csv_text"].encode()).hexdigest() != case["source_csv_sha256"]:
            raise ValueError(f"Source hash mismatch for {case['id']}")
    return bank, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--directory", type=Path, default=HERE)
    args = parser.parse_args()
    manifest = freeze(args.directory) if args.freeze else load_bank(args.directory)[1]
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
