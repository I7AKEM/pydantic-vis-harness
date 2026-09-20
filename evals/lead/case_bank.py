"""Offline, versioned cases for runtime regression evaluation and future DSPy tuning.

Loading data never constructs a model, reads credentials, or sends data anywhere.
The DSPy examples are inputs + acceptance contracts, not teacher demonstrations.
"""

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BANK = Path(__file__).with_name("case-bank-v1")


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_bank(directory: Path = BANK, *, verify_sources: bool = False) -> dict:
    """Validate the frozen inputs and split membership without importing the runtime."""
    directory = Path(directory)
    cases = json.loads((directory / "cases.json").read_text(encoding="utf-8"))
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    findings = json.loads((directory / "findings.json").read_text(encoding="utf-8"))
    if manifest["schema_version"] != 1 or digest(cases) != manifest["cases_sha256"]:
        raise ValueError("Case bank version or frozen input hash mismatch")
    names = [case["name"] for case in cases]
    sources = manifest["sources"]
    if len(names) != len(set(names)) or set(names) != set(sources):
        raise ValueError("Duplicate case or source identity mismatch")
    if len(cases) != manifest["case_count"]:
        raise ValueError("Case count mismatch")
    membership = manifest["splits"]
    if set(membership) != {"train", "validation", "heldout"} or membership["heldout"]:
        raise ValueError("This development bank contains no independent held-out set")
    assigned = membership["train"] + membership["validation"]
    if len(assigned) != len(set(assigned)) or set(assigned) != set(names):
        raise ValueError("Every source case must occur in exactly one tuning split")
    group_splits = {}
    for split, split_names in membership.items():
        for name in split_names:
            source = sources[name]
            # Both semantic-table duplicates and byte-identical files stay together.
            for group in ("table:" + source["group_id"], "file:" + source["csv_sha256"]):
                if group in group_splits and group_splits[group] != split:
                    raise ValueError("A source group crosses train and validation")
                group_splits[group] = split
    segment_names = []
    for segment in manifest["segments"]:
        selected = [case for case in cases if case["name"] in segment["names"]]
        if [case["name"] for case in selected] != segment["names"] or digest(selected) != segment["cases_sha256"]:
            raise ValueError("Frozen study segment changed")
        segment_names.extend(segment["names"])
    if len(segment_names) != len(set(segment_names)) or set(segment_names) != set(names):
        raise ValueError("Study segments do not partition the bank")
    finding_ids = [finding["id"] for finding in findings]
    if len(finding_ids) != len(set(finding_ids)):
        raise ValueError("Duplicate finding ID")
    for finding in findings:
        if not finding["case_names"] or not set(finding["case_names"]) <= set(names):
            raise ValueError("Finding refers to an unknown case")
        if finding["status"] != "agent_audited" or not finding["acceptance"] or not finding["evidence"]:
            raise ValueError("Findings need explicit provenance and acceptance criteria")
    for case in cases:
        if case.get("heldout") or not case.get("turns"):
            raise ValueError("Cases must be development conversations")
        if verify_sources:
            actual = hashlib.sha256(Path(case["csv"]).read_bytes()).hexdigest()
            if actual != sources[case["name"]]["csv_sha256"]:
                raise ValueError(f"Source CSV changed: {case['name']}")
    return {"cases": cases, "manifest": manifest, "findings": findings}


def select_cases(bank: dict, selection: str = "all") -> list[dict]:
    """Return existing-runner-compatible cases, preserving the original gates."""
    if selection == "all":
        names = {case["name"] for case in bank["cases"]}
    elif selection == "regression":
        names = {name for finding in bank["findings"] for name in finding["case_names"]}
    elif selection in {"train", "validation"}:
        names = set(bank["manifest"]["splits"][selection])
    else:
        raise ValueError("Choose all, regression, train, or validation; no independent heldout exists")
    return deepcopy([case for case in bank["cases"] if case["name"] in names])


def dspy_examples(split: str, directory: Path = BANK) -> list:
    """Task inputs only enter the program; expectations/diagnoses remain metric metadata.

    This is a data adapter, NOT a GEPA run or a proxy for end-to-end correctness.
    No answer/spec/verdict is promoted from a model's output to a gold label.
    """
    if split not in {"train", "validation"}:
        raise ValueError("DSPy tuning loads train or validation only, never all/regression/heldout")
    import dspy

    bank = load_bank(directory)
    examples = []
    for case in select_cases(bank, split):
        name = case["name"]
        # Deliberate allowlist: never pass audit, expected chart, score, or diagnosis.
        inputs = {key: deepcopy(case[key]) for key in ("csv", "brief", "caller_kind", "caller_identity")
                  if key in case}
        inputs["messages"] = [turn["message"] for turn in case["turns"]]
        examples.append(dspy.Example(
            case_input=inputs,
            case_id=name,
            expectations=[{key: deepcopy(value) for key, value in turn.items() if key != "message"}
                          for turn in case["turns"]],
            source=deepcopy(bank["manifest"]["sources"][name]),
            findings=[deepcopy(f) for f in bank["findings"] if name in f["case_names"]],
            gold_output_status="not_provided; contracts_and_diagnostics_only",
        ).with_inputs("case_input"))
    return examples


def validate_evidence(bank: dict, root: Path = ROOT) -> None:
    """Verify local links/hashes; never fetch evidence or rescore observations."""
    runs = {}
    for evidence in bank["manifest"]["result_files"]:
        path = root / evidence["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != evidence["sha256"]:
            raise ValueError(f"Raw result file changed: {evidence['path']}")
        records = json.loads(path.read_text(encoding="utf-8"))["cases"]
        if len(records) != evidence["case_count"]:
            raise ValueError("Saved run count mismatch")
        runs[evidence["path"]] = (evidence["arm"], {record["name"]: record for record in records})
    for name, source in bank["manifest"]["sources"].items():
        for observation in source["observations"]:
            arm, records = runs[observation["result_file"]]
            record = records[name]
            if arm != observation["arm"] or record["source_csv_sha256"] != source["csv_sha256"]:
                raise ValueError("Observation source/arm mismatch")
            result_path = Path(observation["result_file"])
            assets = result_path.parent / (result_path.stem + "-assets")
            expected_images = [str(assets / asset) for asset in record.get("assets", [])
                               if asset.endswith(".png")]
            if observation["images"] != expected_images:
                raise ValueError("Image evidence does not belong to the saved case")
            for relative in [observation["checkpoint"], *observation["images"]]:
                if not (root / relative).is_file():
                    raise ValueError(f"Missing local evidence: {relative}")
            checkpoint = json.loads((root / observation["checkpoint"]).read_text(encoding="utf-8"))
            if checkpoint["name"] != name or checkpoint["source_csv_sha256"] != source["csv_sha256"]:
                raise ValueError("Checkpoint belongs to a different source case")
    for finding in bank["findings"]:
        for relative in finding["evidence"]:
            if not (root / relative).is_file():
                raise ValueError(f"Missing finding evidence: {relative}")


def summary(bank: dict) -> dict:
    sources = bank["manifest"]["sources"].values()
    observed = sum(bool(source["observations"]) for source in sources)
    return {
        "cases": len(bank["cases"]),
        "cases_with_saved_runs": observed,
        "cases_without_saved_runs": len(bank["cases"]) - observed,
        "saved_runs": sum(len(source["observations"]) for source in sources),
        "splits": {split: len(names) for split, names in bank["manifest"]["splits"].items()},
        "dispositions": dict(Counter(case["turns"][0]["disposition"] for case in bank["cases"])),
        "documented_findings": len(bank["findings"]),
        "regression_cases": len(select_cases(bank, "regression")),
        "gold_model_outputs": 0,
        "model_calls": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", type=Path, default=BANK)
    parser.add_argument("--check-sources", action="store_true")
    parser.add_argument("--check-evidence", action="store_true")
    parser.add_argument("--cases", choices=("all", "regression", "train", "validation"),
                        help="Print runner-compatible JSON instead of the inventory")
    args = parser.parse_args()
    bank = load_bank(args.bank, verify_sources=args.check_sources)
    if args.check_evidence:
        validate_evidence(bank)
    payload = select_cases(bank, args.cases) if args.cases else summary(bank)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
