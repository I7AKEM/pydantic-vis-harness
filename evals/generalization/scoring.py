"""Versioned, deterministic contract evidence; never treat the online judge as gold."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from evals.generalization.bank import canonical_bytes

SCORER_VERSION = "transfer-contract-v1"


def observations(columns: list[str], rows: list[list], canonical: dict[str, str] | None = None) -> list[str]:
    """Order-independent rows, preserving column identities and all cell values."""
    mapping = canonical or {}
    normalized = []
    for row in rows:
        if len(row) != len(columns):
            raise ValueError("Ragged evidence table")
        value = {mapping.get(column, column): cell for column, cell in zip(columns, row, strict=True)}
        # CSV integer 2 and returned numeric 2.0 denote the same number; strings
        # (including leading-zero identifiers) are never coerced to numbers.
        value = {key: int(cell) if isinstance(cell, float) and cell.is_integer() else cell for key, cell in value.items()}
        normalized.append(canonical_bytes(value).decode())
    return sorted(normalized)


def _reply_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(_reply_text(value.get(key)) for key in ("card", "message", "reply", "text", "output"))
    return ""


def select_artifact(record: dict) -> tuple[dict | None, str]:
    artifacts = record.get("artifacts", [])
    turns = record.get("turns", [])
    selected = turns[-1].get("artifact_id") if turns else None
    matching = [artifact for artifact in artifacts if artifact.get("artifact_id") == selected]
    if len(matching) == 1:
        return matching[0], "explicit_final_tool_artifact"
    reply = _reply_text(turns[-1].get("reply")) if turns else ""
    matching = [artifact for artifact in artifacts if artifact.get("png_url") and artifact["png_url"] in reply]
    if len(matching) == 1:
        return matching[0], "unique_artifact_link_in_final_reply"
    if len(artifacts) == 1:
        return artifacts[0], "only_persisted_artifact_delivery_checked_separately"
    return None, "missing_or_ambiguous_published_artifact"


def _parts(record: dict) -> list[dict]:
    return [part for turn in record.get("turns", []) for message in turn.get("messages", [])
            for part in message.get("parts", [])]


def render_assets(case: dict, root: Path) -> list[dict]:
    """Retain all images/configs, not only the last accepted output."""
    directory = root / case["id"] / "renders"
    result = []
    if not directory.is_dir():
        return result
    for path in sorted(directory.glob("*/chart.png"), key=lambda item: (item.stat().st_mtime_ns, item.parent.name)):
        content = path.read_bytes()
        valid = content.startswith(b"\x89PNG\r\n\x1a\n") and len(content) >= 24
        result.append({"render_id": path.parent.name, "path": str(path.relative_to(root)),
                       "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content),
                       "width": int.from_bytes(content[16:20], "big") if valid else 0,
                       "height": int.from_bytes(content[20:24], "big") if valid else 0,
                       "valid_png_header": valid,
                       "config_sha256": hashlib.sha256((path.parent / "config.json").read_bytes()).hexdigest()
                       if (path.parent / "config.json").is_file() else None})
    return result


def score_case(case: dict, record: dict, evidence_root: Path) -> dict:
    # Import after the launcher selects the baseline/candidate runtime. Parsing
    # is executable evidence, not a second LLM opinion.
    from vis_agent.designer.syntax import parse

    contract = case["contract"]
    artifact, selection = select_artifact(record)
    turns = record.get("turns", [])
    turn = turns[-1] if turns else {}
    reply = _reply_text(turn.get("reply"))
    parts = _parts(record)
    calls = Counter(part.get("tool_name") for part in parts if part.get("part_kind") == "tool-call")
    assets = render_assets(case, evidence_root)
    checks = {name: False for name in ("artifact_persisted", "source_fidelity", "source_units", "chart_appropriate",
                                       "bindings", "visible_fields", "measure_selection", "literal_codes",
                                       "no_unrequested_limit", "sort", "render_file", "delivered_link", "final_reply", "completed")}
    checks["artifact_persisted"] = artifact is not None
    checks["final_reply"] = bool(reply.strip())
    error = turn.get("error") or record.get("error") or record.get("evaluation_error")
    checks["completed"] = not error
    diagnostics, canonical_source, visible_canonical, measures_canonical = [], [], [], []
    chart = None
    if artifact:
        report = artifact.get("report") or {}
        table = report.get("result") or {}
        columns, rows = table.get("columns", []), table.get("rows", [])
        try:
            checks["source_fidelity"] = (set(columns) == set(case["source_columns"])
                                          and observations(columns, rows) == observations(case["source_columns"], case["source_rows"]))
            canonical_source = observations(columns, rows, case["canonical_columns"])
        except (TypeError, ValueError) as exc:
            diagnostics.append(f"Source evidence error: {exc}")
        metadata = {column["name"]: column for column in (report.get("analysis") or {}).get("columns", [])}
        checks["source_units"] = all(metadata.get(column, {}).get("unit") == unit for column, unit in contract["units"].items())
        spec_text = (artifact.get("design") or {}).get("spec")
        try:
            spec = parse(spec_text or "")
            chart = spec.type
            visible = set(spec.bind.values()) | set(spec.fold)
            measures = {value for key, value in spec.bind.items() if key in {"value", "value2", "x", "y"}}
            measures.update(spec.fold)
            for card in spec.cards:
                visible.update([card.value, *card.context, *card.support])
                measures.add(card.value)
            if spec.type == "table":
                visible = set(columns)
                measures = {column for column in columns if column in contract["units"]}
            checks["chart_appropriate"] = spec.type in contract["allowed_charts"]
            checks["bindings"] = all(spec.bind.get(role) == column for role, column in contract["required_bindings"].items())
            checks["visible_fields"] = set(contract["required_visible_columns"]) <= visible
            checks["measure_selection"] = (set(contract["primary_measures"]) <= measures
                                              and not set(contract["forbidden_measures"]) & measures)
            checks["literal_codes"] = all(
                not any(mapped != raw for raw, mapped in spec.value_labels.get(column, {}).items())
                for column in contract["literal_columns"])
            checks["no_unrequested_limit"] = spec.limit is None or spec.limit >= len(case["source_rows"])
            checks["sort"] = contract["sort"] is None or spec.sort == contract["sort"]
            visible_canonical = sorted(case["canonical_columns"].get(column, column) for column in visible)
            measures_canonical = sorted(case["canonical_columns"].get(column, column) for column in measures)
        except Exception as exc:
            diagnostics.append(f"Executable design evidence error: {type(exc).__name__}: {exc}")
        url = artifact.get("png_url")
        target = next((asset for asset in assets if url == f"/renders/{asset['render_id']}/chart.png"), None)
        checks["render_file"] = bool(target and target["valid_png_header"] and target["width"] and target["height"])
        checks["delivered_link"] = bool(url and url in reply)
    diagnostics.extend(name for name, passed in checks.items() if not passed)
    usage = turn.get("usage") or {}
    return {"id": case["id"], "family": case["family"], "goal": case["goal"], "variant": case["variant"],
            "scorer_version": SCORER_VERSION, "checks": checks, "deterministic_contract_pass": all(checks.values()),
            "visual_quality_verified": False, "visual_audit_status": "independent_image_audit_required",
            "human_gold": False, "diagnostics": diagnostics, "error": error,
            "timed_out": bool(error and "TimeoutError" in str(error)), "seconds": turn.get("seconds"),
            "within_60s": isinstance(turn.get("seconds"), (float, int)) and turn["seconds"] <= 60,
            "framework_requests": usage.get("requests"), "framework_tool_calls": usage.get("tool_calls"),
            "attempted_tool_calls_captured": dict(calls), "provider_attempt_count_complete": False,
            "attempt_count_note": "Framework usage may omit an in-flight cancelled provider attempt; timeouts remain failures.",
            "chart": chart, "artifact_selection": selection, "artifact_id": artifact.get("artifact_id") if artifact else None,
            "canonical_source": canonical_source, "canonical_visible_columns": visible_canonical,
            "canonical_measures": measures_canonical,
            "online_reviewer": artifact.get("review") if artifact else None,
            "render_assets": assets, "source_csv_sha256": case["source_csv_sha256"]}


def score_pairs(bank: dict, scores: list[dict]) -> list[dict]:
    indexed = {score["id"]: score for score in scores}
    result = []
    for pair in bank["pairs"]:
        members = [indexed.get(key) for key in pair["members"]]
        complete = all(member is not None for member in members)
        same_source = bool(complete and members[0]["canonical_source"] and members[0]["canonical_source"] == members[1]["canonical_source"])
        contracts = bool(complete and all(member["deterministic_contract_pass"] for member in members))
        result.append({"id": pair["id"], "kind": pair["kind"], "members": pair["members"],
                       "complete": complete, "equivalent_canonical_source": same_source,
                       "both_goal_contracts_met": contracts, "metamorphic_contract_pass": same_source and contracts,
                       "visual_quality_verified": False,
                       "chart_equality_required": False, "pixel_equality_required": False})
    return result


def summarize(bank: dict, scores: list[dict]) -> dict:
    def percentile(values, fraction):
        if not values:
            return None
        ordered = sorted(values)
        return ordered[max(0, min(len(ordered) - 1, __import__("math").ceil(len(ordered) * fraction) - 1))]
    seconds = [score["seconds"] for score in scores if isinstance(score.get("seconds"), (float, int))]
    pairs = score_pairs(bank, scores)
    return {"attempts": len(scores), "deterministic_contract_pass": sum(score["deterministic_contract_pass"] for score in scores),
            "visual_quality_verified": False, "timeouts": sum(score["timed_out"] for score in scores),
            "within_60s": sum(score["within_60s"] for score in scores),
            "median_seconds": percentile(seconds, .5), "p95_seconds": percentile(seconds, .95),
            "latency_censored": any(score["timed_out"] for score in scores),
            "checks_passed": {key: sum(score["checks"][key] for score in scores) for key in (scores[0]["checks"] if scores else {})},
            "families": {family["id"]: {"attempts": sum(score["family"] == family["id"] for score in scores),
                                         "contract_pass": sum(score["family"] == family["id"] and score["deterministic_contract_pass"] for score in scores)}
                         for family in bank["families"]},
            "pairs": pairs, "limitations": ["Synthetic challenge evidence, not a population accuracy estimate.",
                                                "No human-labelled visual gold; deterministic checks do not prove image legibility or factual prose.",
                                                "Online model review verdicts are recorded, never used as an independent correctness oracle."]}
