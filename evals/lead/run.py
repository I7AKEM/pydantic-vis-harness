"""Evaluate scripted lead conversations against deterministic samples from the development CSV corpus."""

import argparse
import asyncio
import json
import random
import math
import re
import shutil
import tempfile
import hashlib
from collections import Counter
from time import perf_counter
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from pydantic_ai import capture_run_messages
from pydantic_ai.messages import ToolCallPart, ToolReturnPart, ModelMessagesTypeAdapter
from pydantic_ai.usage import RunUsage, UsageLimits
from pydantic_core import to_jsonable_python

from evals.designer.agent.corpus_tools.select import CORPUS, read_manifest
from vis_agent.analyst.agent import ARABIC
from vis_agent.analyst.checks import numeric_mention_direction
from vis_agent.deps import AppDeps
import vis_agent.lead
from vis_agent.models import DataBrief
from vis_agent.providers import teams_from_env
from vis_agent.requests.service import REQUEST_LIMIT, TOOL_LIMIT
from vis_agent.requests.store import RequestStore
from vis_agent.store import DatasetStore
from vis_agent.units import COUNT_NOUNS, canonical_unit, display_unit
from vis_agent.designer.syntax import parse
from vis_agent.designer.models import SpecError
from evals.analyst.run import tables_match
from evals.designer.agent.indicator.scoring import numeric_text_matches

ROOT = Path(__file__).resolve().parents[2]
DATA_TOOLS = {"draw", "answer_question", "revise", "resume"}
OUTCOME_TOOLS = DATA_TOOLS | {"publish_visualization", "ask_user"}
FIDELITY_KEYS = ("fidelity_ok", "delivery_ok", "answer_fidelity_ok", "analysis_reuse_ok", "language_ok",
                 "source_fidelity_ok", "delegation_ok", "chart_ok", "binding_ok", "axis_titles_ok", "labels_ok",
                 "flow_ok", "review_ok", "latency_ok", "render_evidence_ok", "visible_columns_ok",
                 "repetition_ok", "reply_ok", "semantic_fidelity_ok")


def source_signature(columns: list[str], rows: list[list]) -> dict:
    """Hash the complete typed table, never the lead's bounded preview."""
    canonical = json.dumps({"columns": columns, "rows": rows}, ensure_ascii=False, separators=(",", ":"))
    return {"columns": columns, "row_count": len(rows),
            "sha256": hashlib.sha256(canonical.encode()).hexdigest()}


def visible_columns(artifact: dict) -> set[str]:
    """Columns whose values actually enter the static chart, not just its stored CSV."""
    text = artifact.get("spec")
    if not isinstance(text, str) or not text.strip():
        return set()
    try:
        spec = parse(text)
    except (KeyError, TypeError, SpecError):
        return set()
    if spec.type == "table":
        return {column["name"] for column in artifact.get("columns", [])}
    used = set(spec.bind.values()) | set(spec.fold)
    for card in spec.cards:
        used.update([card.value, *card.context, *card.support])
    return used


def approved_review(artifact: dict) -> bool:
    report = artifact.get("review") or {}
    review = report.get("review") or {}
    return (report.get("status") == "reviewed" and review.get("verdict", report.get("verdict")) == "pass"
            and not any(f.get("level", f.get("severity")) == "error" for f in review.get("findings", [])))


def load_cases(path: Path | None = None) -> list[dict]:
    # Cases marked heldout are evaluation-only; exclude them from any future prompt tuning.
    return json.loads((path or Path(__file__).with_name("cases.json")).read_text(encoding="utf-8"))


def observed_outcome(value: dict, last_tool: str) -> str:
    artifact = value.get("artifact")
    if value.get("status") == "failed" or value.get("error"):
        return "failure"
    if value.get("clarification"):
        return "clarification"
    if artifact:
        if artifact.get("no_chart_reason"):
            return "fallback_table"
        if artifact.get("chart") == "indicator":
            return "unavailable_indicator" if any(cell is None for row in artifact.get("rows", []) for cell in row) else "indicator"
        return "artifact"
    return "table" if last_tool == "answer_question" and value.get("rows") else "text"


def metric_values_match(expected: dict, artifact: dict) -> bool:
    """Check e2e numeric bindings without requiring a model's SQL aliases to match gold aliases."""
    try:
        spec = parse(artifact["spec"])
        if spec.type != "indicator" or len(spec.cards) != expected["card_count"]:
            return False
        columns = artifact["columns"]
        metadata = {column["name"]: column for column in columns}
        if artifact.get("row_count") != 1 or len(artifact["rows"]) != 1:
            return False
        row = dict(zip(metadata, artifact["rows"][0]))
        actual = [(row[c.value], metadata[c.value].get("unit")) for c in spec.cards]
        wanted = list(zip(expected["values"], expected.get("units", [None] * expected["card_count"])))
        def equal(a, b):
            return a is None and b is None or isinstance(a, (int, float)) and not isinstance(a, bool) and b is not None and math.isclose(a, b, rel_tol=1e-7, abs_tol=1e-10)
        def dimension(unit):
            if unit is not None and any(unit.strip().casefold() in aliases for aliases, *_ in COUNT_NOUNS.values()):
                return None
            return canonical_unit(display_unit(unit))
        def unit_matches(actual, expected):
            for aliases, *_ in COUNT_NOUNS.values():
                if expected is not None and expected.strip().casefold() in aliases:
                    return actual is not None and actual.strip().casefold() in aliases
            return dimension(actual) == dimension(expected)
        for number, unit in wanted:
            match = next((i for i, (value, actual_unit) in enumerate(actual) if equal(value, number) and unit_matches(actual_unit, unit)), None)
            if match is None:
                return False
            actual.pop(match)
        support = [row[name] for c in spec.cards for name in c.support]
        return all(any(equal(value, expected) for value in support) for expected in expected.get("support_values", []))
    except (KeyError, TypeError, ValueError, SpecError):
        return False


def _without_column_identifiers(text: str, artifact: dict) -> str:
    """Ignore a literal known identifier, never all numbers contained in its name.

    A column named ``count_under_30`` can be quoted as an identifier. This must
    not authorize an unrelated claim of 30 records, nor an unknown identifier
    such as ``count_under_31``. Numeric column names and ordinary prose headings
    are deliberately not masked.
    """
    names = [column.get("name", "") for column in artifact.get("columns", [])]
    for name in sorted(names, key=len, reverse=True):
        if name.isidentifier() and any(character.isdigit() for character in name):
            text = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", " ", text)
    return text


def answer_numbers_match(reply: str | None, artifact: dict, question: str) -> bool:
    """Check numeric claims against saved values, without permitting implicit 100x scaling.

    This is a factual check, not a judge of whether the wording explains the answer well.
    Links/IDs and list ordinals are removed before examining user-visible claims.
    """
    if not reply:
        return False
    text = re.sub(r"\]\([^)]*\)", "]", reply)
    # A raw image URL, or a URL used as a Markdown link label, is an identifier,
    # not a numerical claim. Keep ordinary link labels (e.g. [41](...)) visible.
    text = re.sub(r"https?://[^\s<>()\[\]`]+|/renders/[A-Za-z0-9_-]+/chart\.(?:png|html)"
                  r"(?:[?#][^\s<>()\[\]`]+)?", "", text)
    text = re.sub(r"\b(?:art|rq|ds)_[A-Za-z0-9]+\b|#[A-Fa-f0-9]{6}\b", "", text)
    text = re.sub(r"^\s*\d+[.)]\s+", "", text, flags=re.MULTILINE)
    text = _without_column_identifiers(text, artifact)
    text = text.replace("−", "-")
    # A requested period/age range is context, not a negative data value. Match
    # the complete range so an unrelated fabricated measurement is not excused.
    range_pattern = re.compile(r"(?<![\d.])(\d+)\s*[-–—]\s*(\d+)(?!\d|\.\d)")
    context_text = question + " " + (artifact.get("question") or "")
    for row in artifact.get("rows", []):
        context_text += " " + " ".join(value for value in row if isinstance(value, str))
    context_range_pattern = re.compile(
        r"(?<![\d.,٬٫])(\d+)\s*(?:[-–—]|\bto\b|\band\b|و|إلى|الى)\s*(\d+)(?!\d|[.,٬٫]\d)", re.I,
    )
    ranges = {tuple(match.groups()) for match in context_range_pattern.finditer(context_text)}
    text = range_pattern.sub(lambda match: "" if tuple(match.groups()) in ranges else match[0], text)
    number = re.compile(r"[-+]?(?:\d[\d,٬]*)(?:[.٫]\d+)?(?:[eE][-+]?\d+)?(?:[KMBT])?")
    # Remove identifiers from the prompt too: its reference to count_under_30
    # must not globally whitelist the measurement 30 in the final answer.
    context = set(number.findall(_without_column_identifiers(
        question + " " + (artifact.get("question") or ""), artifact)))
    # Runtime warnings can quote verified source totals that are outside the filtered result.
    for warning in artifact.get("warnings", []):
        context.update(number.findall(warning))
    candidates = [v for row in artifact.get("rows", []) for v in row
                  if isinstance(v, (int, float)) and not isinstance(v, bool)]
    signed_values = list(candidates)
    candidates.extend(artifact[key] for key in ("row_count", "version") if isinstance(artifact.get(key), int))
    for index, column in enumerate(artifact.get("columns", [])):
        # Category cardinality is a verifiable presentation fact, not a newly
        # calculated measure. The same fact is in the runtime's table profile.
        if column.get("kind") in {"category", "time"}:
            candidates.append(len({row[index] for row in artifact.get("rows", [])
                                   if len(row) > index and row[index] is not None}))
        context.update(number.findall(column.get("unit") or ""))
        context.update(re.findall(r"(?:^|_)per_(\d+)(?:_|$)", column.get("name", "")))
    for row in artifact.get("rows", []):
        for value in row:
            if isinstance(value, str):
                context.update(number.findall(value))
    for mention in number.finditer(text):
        token = mention[0]
        start = mention.start() + (1 if token.startswith('+') else 0)
        direction = numeric_mention_direction(text, start, mention.end())
        if direction == 0:
            return False
        if direction is not None:
            signed = ('-' if direction == -1 else '') + token.lstrip('+')
            if not any(numeric_text_matches(signed, value) for value in signed_values):
                return False
        elif token not in context and not any(numeric_text_matches(token, value) for value in candidates):
            return False
    return True


def semantic_fidelity(reply: str | None, artifact: dict, contract: dict,
                      brief: DataBrief | dict | None = None) -> tuple[bool, list[str]]:
    """Check an explicit, bounded unknown-code regression contract.

    This is not a semantic LLM judge or a universal ban on translation. The case
    author supplies exact codes and known prohibited expansions. Established
    meanings or approved display labels in the authoritative brief take
    precedence. No meanings are inferred from the code spelling or case ID.
    """
    unknown = contract.get("unknown_codes")
    expansions = contract.get("forbidden_expansions", {})
    if not isinstance(unknown, dict) or not unknown or not isinstance(expansions, dict):
        raise ValueError("semantic_fidelity requires nonempty unknown_codes and a forbidden_expansions mapping")
    for column, codes in unknown.items():
        if not isinstance(column, str) or not isinstance(codes, list) or not codes or not all(
                isinstance(code, str) and code for code in codes):
            raise ValueError("unknown_codes must map column names to nonempty lists of exact string codes")
    for column, mappings in expansions.items():
        if column not in unknown or not isinstance(mappings, dict):
            raise ValueError("forbidden_expansions must refer to an unknown_codes column")
        for code, labels in mappings.items():
            if code not in unknown[column] or not isinstance(labels, list) or not labels or not all(
                    isinstance(label, str) and label.strip() for label in labels):
                raise ValueError("forbidden_expansions must map exact declared codes to nonempty label lists")
    metadata = brief.model_dump() if isinstance(brief, DataBrief) else (brief or {})
    diagnostics = []
    if not isinstance(reply, str) or not reply.strip():
        diagnostics.append("Missing final prose for the required semantic check.")
    columns = [column.get("name") for column in artifact.get("columns", [])]
    if not artifact.get("rows") or any(column not in columns for column in unknown):
        diagnostics.append("Missing source columns or rows for the required code-semantics check.")
    try:
        spec = parse(artifact["spec"])
    except (KeyError, TypeError, ValueError, SpecError):
        return False, diagnostics + ["Missing executable design for the required code-semantics check."]

    # Remove URL targets/identifiers, not visible Markdown labels. These are
    # annotations and links, not assertions about a category's meaning.
    prose = re.sub(r"\]\([^)]*\)", "]", reply or "")
    prose = re.sub(r"https?://[^\s<>()\[\]`]+|/renders/[^\s<>()\[\]`]+", "", prose)
    # A narrowly phrased denial must not be mislabelled as an asserted mapping.
    # Split adversatives and sentence/clause boundaries so a denial does not
    # excuse a subsequent assertion ("No mapping supplied; F means female").
    clauses = re.split(r"[.!?؟\n؛;,،]|\b(?:but|however)\b|(?:ولكن|لكن)", prose, flags=re.I)
    denial = re.compile(
        r"\b(?:no|without)\s+(?:(?:supplied|provided|explicit)\s+)?(?:codebook|mapping|definition|meaning|interpretation)\b"
        r"|\b(?:not|never|cannot|can't|don't)\s+(?:infer|assume|interpret|decode|translate|mean|equate|map)\b"
        r"|\b(?:mapping|codebook|meaning|definition)\b.{0,30}\b(?:not supplied|not provided|unknown|unavailable|missing)\b"
        r"|(?:دون|بدون)\s+(?:افتراض|تفسير|ترجمة|معنى|تعريف|ربط|قاموس|تحديد)"
        r"|(?:لا|لم|لن)\s+(?:نفترض|أفترض|افترض|نستنتج|أستنتج|استنتج|يعني|تعني|نعرف|أعرف|اعرف)"
        r"|(?:لا|لم)\s+(?:يوجد|يتوفر|يرد|ترد)\s+(?:تعريف|معنى|قاموس|تفسير)", re.I,
    )
    for column, codes in unknown.items():
        for code in codes:
            meanings = (metadata.get("code_meanings") or {}).get(column, {})
            approved = [labels.get("value_labels", {}).get(column, {}).get(code)
                        for labels in (metadata.get("display_labels") or {}).values()]
            if meanings.get(code) or any(approved):
                # Translation of a supplied meaning is permitted; this specific
                # unknown-code contract cannot judge whether it is accurate.
                continue
            label = spec.value_labels.get(column, {}).get(code)
            if label is not None and label != code:
                diagnostics.append(f"Unmapped code {column}.{code} was relabelled as {label!r} in the design.")
            for expansion in expansions.get(column, {}).get(code, []):
                pattern = re.compile(r"(?<!\w)" + re.escape(expansion) + r"(?!\w)", re.I)
                # An incidental "no codebook" caveat does not excuse an
                # explicit assertion such as "F means female without a map".
                explicit = re.compile(
                    r"(?<!\w)(?:" + re.escape(code) + r"\s*(?:[=:]|means?|is|represents?|denotes?|stands for|يعني|تعني|يمثل|تمثل|هو|هي)\s*"
                    r"(?:the\s+)?" + re.escape(expansion) + r"(?!\w)|"
                    + re.escape(code) + r"\s*\(\s*" + re.escape(expansion) + r"\s*\)|"
                    + re.escape(expansion) + r"\s*\(\s*" + re.escape(code) + r"\s*\))", re.I,
                )
                def asserts(clause: str) -> bool:
                    if not pattern.search(clause):
                        return False
                    mapping = explicit.search(clause)
                    if mapping:
                        prefix = clause[:mapping.start()]
                        # "Cannot infer whether F means female" is a denial,
                        # unlike "No mapping supplied and F means female".
                        subordinate = re.search(r"\b(?:whether|that|infer|assume|interpret|decode|translate)\s*$|(?:أن|ان)\s*$", prefix, re.I)
                        return not (subordinate and denial.search(prefix))
                    return not bool(denial.search(clause))

                asserted = any(asserts(clause) for clause in clauses)
                chart_text = " ".join(filter(None, [spec.title, spec.subtitle, spec.description,
                                                    spec.axis_x_title, spec.axis_y_title, *spec.column_labels.values()]))
                if asserted or pattern.search(chart_text):
                    location = "final prose" if asserted else "design title/description"
                    diagnostics.append(f"Unsupported expansion {expansion!r} for {column}.{code} in {location}; no code meaning was supplied.")
    return not diagnostics, diagnostics


def required_score_keys(expected: dict, tool: str | None = None) -> set[str]:
    """Derive required gates from the case contract, not from returned fields."""
    required = {"tool_ok", "outcome_ok"}
    conditions = {
        "fidelity_ok": "metrics" in expected or expected.get("forbid_indicator") or "expected_rows" in expected,
        "delivery_ok": expected.get("require_delivery") or expected.get("no_image"),
        "answer_fidelity_ok": "metrics" in expected or expected.get("strict_source"),
        "source_fidelity_ok": "source_rows" in expected or expected.get("strict_source"),
        "delegation_ok": expected.get("prepared_csv"), "flow_ok": expected.get("prepared_csv"),
        "chart_ok": "charts" in expected, "binding_ok": "bindings" in expected,
        "language_ok": bool(expected.get("language")), "labels_ok": "display_labels" in expected,
        "axis_titles_ok": "axis_titles" in expected,
        "review_ok": expected.get("review_required") or expected.get("review_pass_required"),
        "render_evidence_ok": expected.get("require_render_evidence"),
        "visible_columns_ok": "visible_columns" in expected,
        "repetition_ok": "max_tool_calls" in expected, "reply_ok": "reply_patterns" in expected,
        "latency_ok": "max_seconds" in expected,
        "semantic_fidelity_ok": "semantic_fidelity" in expected,
        "analysis_reuse_ok": "analysis_reused" in expected,
        "revision_ok": "revision" in expected,
        "redo_ok": "redo_analysis" in expected and (tool == "revise" or not isinstance(expected.get("tool"), list)),
    }
    return required | {name for name, active in conditions.items() if active}


def turn_diagnostics(turn: dict, *, expected: dict | None = None,
                     include_latency: bool = True) -> list[str]:
    """Fail-closed E2E feedback for an optimizer, separate from any scalar reward.

    Historical JSON scores are never rewritten. A saved boolean without its
    required evidence is not sufficient for a new optimization evaluation.
    """
    expected = turn.get("expected", {}) if expected is None else expected
    diagnostics = []
    if not expected or not all(key in expected for key in ("tool", "outcome")):
        diagnostics.append("Missing required turn expectation contract.")
    for key in ("error", "evaluation_error"):
        if turn.get(key):
            diagnostics.append(f"{key}: {turn[key]}")
    required = required_score_keys(expected, turn.get("tool"))
    if not include_latency:
        required.discard("latency_ok")
    for key in sorted(required):
        if turn.get(key) is not True:
            state = "failed" if turn.get(key) is False else "missing required evidence"
            diagnostics.append(f"{key}: {state}")
    for key in ("redo_ok", "revision_ok", *FIDELITY_KEYS):
        if key not in required and (key != "latency_ok" or include_latency) and turn.get(key) is False:
            diagnostics.append(f"{key}: failed")
    reply = turn.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        diagnostics.append("Missing substantive final reply.")
    returned = turn.get("tool_return")
    public = returned.get("artifact") if isinstance(returned, dict) else None
    public = public if isinstance(public, dict) else {}
    if expected.get("require_delivery") and not (
            public.get("png_url") and isinstance(reply, str) and public["png_url"] in reply):
        diagnostics.append("Missing delivered image URL in the final reply.")
    if expected.get("no_image") and isinstance(reply, str) and re.search(r"!\[|/renders/[^\s)]+\.png", reply):
        diagnostics.append("This boundary case must not be credited with an image deliverable.")
    if expected.get("forbid_questions") and (turn.get("questioned") or "ask_user" in turn.get("tools_called", [])):
        diagnostics.append("The task forbids clarification questions.")
    if expected.get("strict_source"):
        signature = turn.get("artifact_source_signature")
        signature = signature if isinstance(signature, dict) else {}
        if not (isinstance(signature.get("columns"), list) and signature["columns"]
                and isinstance(signature.get("row_count"), int) and signature["row_count"] >= 0
                and isinstance(signature.get("sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", signature.get("sha256", ""))):
            diagnostics.append("Missing persisted full-table source signature.")
    if expected.get("require_render_evidence"):
        evidence = turn.get("render_evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        if not (all(isinstance(evidence.get(key), int) and evidence[key] > 0 for key in ("width", "height", "bytes"))
                and evidence["bytes"] >= 24
                and evidence.get("url") == public.get("png_url") and evidence.get("url")
                and isinstance(evidence.get("sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", evidence.get("sha256", ""))):
            diagnostics.append("Missing matching persisted PNG evidence.")
    if expected.get("review_required") or expected.get("review_pass_required"):
        review = public.get("review")
        review = review if isinstance(review, dict) else {}
        if review.get("status") != "reviewed" or (expected.get("review_pass_required") and not approved_review(public)):
            diagnostics.append("Missing acceptable review evidence for the delivered artifact.")
    if include_latency and "max_seconds" in expected:
        seconds = turn.get("seconds")
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not math.isfinite(seconds) or seconds < 0:
            diagnostics.append("Missing finite end-to-end latency measurement.")
        elif seconds > expected["max_seconds"]:
            diagnostics.append(f"End-to-end latency {seconds:.2f}s exceeds {expected['max_seconds']}s.")
    if "semantic_fidelity" in expected:
        if not isinstance(turn.get("semantic_diagnostics"), list):
            diagnostics.append("Missing required semantic diagnostics.")
        else:
            diagnostics.extend(turn["semantic_diagnostics"])
    return diagnostics


def turn_passes(turn: dict, *, expected: dict | None = None, include_latency: bool = True) -> bool:
    return not turn_diagnostics(turn, expected=expected, include_latency=include_latency)


def corpus_cases(corpus: Path = CORPUS, count: int = 10, seed: int = 11) -> list[dict]:
    # Preserve manifest order before sampling, as in the Phase 4b lead sample.
    rows = random.Random(seed).sample(read_manifest(corpus / "manifest.jsonl"), count)
    cases = []
    for row in rows:
        csv = corpus / row["csv_path"]
        question = row["occurrences"][0]["question"]
        cases.append({
            "name": "corpus-" + row["dataset_id"], "csv": str(csv),
            "turns": [{"message": question + "\n\nAttached CSV: [" + csv.name
                       + "](/datasets/{dataset_id}/profile)",
                       "tool": ["draw", "answer_question"], "outcome": "answered"}],
        })
    return cases


def score_turn(expected: dict, messages: list, reply: str | None = None, *,
               brief: DataBrief | dict | None = None) -> dict:
    parts = [part for message in messages for part in message.parts]
    calls = [part for part in parts if isinstance(part, ToolCallPart)]
    data_calls = [part for part in calls if part.tool_name in DATA_TOOLS]
    # Routing starts the request; publication or a question is the lead's final decision.
    call = data_calls[0] if data_calls else None
    outcome_calls = [part for part in calls if part.tool_name in OUTCOME_TOOLS]
    last = outcome_calls[-1] if outcome_calls else None
    returned = next((part for part in parts if isinstance(part, ToolReturnPart) and last is not None
                     and part.tool_call_id == last.tool_call_id and part.tool_name == last.tool_name), None)
    content = returned.content if returned is not None else None
    if hasattr(content, "model_dump"):
        content = content.model_dump(mode="json")
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except ValueError:
            pass
    value = content if isinstance(content, dict) else {}
    tool = call.tool_name if call is not None else "none"
    args = call.args_as_dict() if call is not None else {}
    last_tool = last.tool_name if last is not None else "none"
    artifact = value.get("artifact")
    questioned = value.get("clarification") is not None
    outcomes = {
        "artifact": artifact is not None,
        # Repair cases accept a delivered artifact, including a table when a chart cannot fit.
        "chart": artifact is not None,
        "question": questioned,
        "artifact_or_question": artifact is not None or questioned,
        # A corpus question over a result-table export may be drawn, asked about, or answered with a table.
        "answered": artifact is not None or questioned
        or (last_tool == "answer_question" and bool(value.get("rows"))),
        "table": last_tool == "answer_question" and bool(value.get("rows")),
        # The lead answered in words: no data tool, or one that returned neither an artifact nor a question
        # (a resume with nothing to continue, for example).
        "text": call is None or (artifact is None and not questioned),
        "indicator": isinstance(artifact, dict) and artifact.get("chart") == "indicator"
        and bool(artifact.get("png_url")) and not artifact.get("no_chart_reason"),
        "failure": observed_outcome(value, last_tool) == "failure",
        "fallback": observed_outcome(value, last_tool) == "fallback_table",
    }
    # Audited non-chart requests are deliberately not credited as charts. They
    # need a substantive final answer, no clarification, and the case's stated
    # limitation/content checks. An exception is rejected by run_case below.
    outcomes["handled"] = bool(reply and reply.strip()) and not questioned
    if expected.get("disposition") in {"text", "source_insufficient", "unsupported"}:
        outcomes["handled"] = outcomes["handled"] and not bool(artifact and artifact.get("png_url"))
    accepted = expected["tool"] if isinstance(expected["tool"], list) else [expected["tool"]]
    # redo_analysis is judged only when a revision was expected and made; a turn that accepts resume or
    # revise (an answer that may continue a question or change a delivered chart) judges it on revise alone.
    redo_ok = None
    if "redo_analysis" in expected and (tool == "revise" or not isinstance(expected["tool"], list)):
        redo_ok = tool == "revise" and args.get("redo_analysis") is expected["redo_analysis"]
    fidelity_ok = metric_values_match(expected["metrics"], artifact or {}) if "metrics" in expected else None
    if expected.get("forbid_indicator"):
        fidelity_ok = bool(artifact) and artifact.get("chart") != "indicator"
    if "expected_rows" in expected:
        rows = value.get("rows") or []
        fidelity_ok = bool(rows) and bool(tables_match({"columns": list(range(len(expected["expected_rows"][0]))),
            "rows": expected["expected_rows"], "strict_scale": True},
            {"columns": list(range(len(rows[0]))), "rows": rows}))
    delivery_ok = None
    if expected.get("require_delivery"):
        delivery_ok = bool(reply and artifact and artifact.get("png_url") and artifact["png_url"] in reply)
    if expected.get("no_image"):
        delivery_ok = bool(reply) and not bool(re.search(r"!\[|/renders/[^\s)]+\.png", reply))
    answer_fidelity_ok = answer_numbers_match(reply, artifact or {}, expected.get("message", "")) if "metrics" in expected else None
    language_ok = None
    if expected.get("language"):
        try:
            spec = parse((artifact or {})["spec"])
            language_ok = spec.language == expected["language"] and (
                bool(ARABIC.search(spec.title or "")) if expected["language"] == "ar"
                else not bool(ARABIC.search(spec.title or "")))
        except (KeyError, TypeError, SpecError):
            language_ok = False
    source_fidelity_ok = None
    if "source_rows" in expected:
        source_fidelity_ok = bool(artifact) and artifact.get("rows") == expected["source_rows"]
        if "source_columns" in expected:
            source_fidelity_ok = source_fidelity_ok and [c["name"] for c in artifact.get("columns", [])] == expected["source_columns"]
    delegation_ok = None
    flow_ok = None
    if expected.get("prepared_csv"):
        delegation_ok = not any(c.tool_name in {"consult_analyst", "profile_csv", "ask_user"} for c in calls)
        flow = [c.tool_name for c in calls]
        required = ["draw", "design_visualization", "render_visualization", "publish_visualization"]
        positions = [flow.index(name) for name in required if name in flow]
        flow_ok = len(positions) == len(required) and positions == sorted(positions)
    chart_ok = (bool(artifact) and artifact.get("chart") in expected["charts"]) if "charts" in expected else None
    binding_ok = None
    if "bindings" in expected:
        try:
            bindings = parse((artifact or {})["spec"]).bind
            binding_ok = all(bindings.get(role) == column for role, column in expected["bindings"].items())
        except (KeyError, TypeError, SpecError):
            binding_ok = False
    review_ok = None
    if expected.get("review_required"):
        names = [c.tool_name for c in calls]
        review_ok = (bool(artifact) and (artifact.get("review") or {}).get("status") == "reviewed"
                     and "review_visualization" in names and "publish_visualization" in names
                     and names.index("review_visualization") < names.index("publish_visualization"))
    if expected.get("review_pass_required"):
        names = [c.tool_name for c in calls]
        last_position = lambda name: max((i for i, value in enumerate(names) if value == name), default=-1)
        last_render = last_position("render_visualization")
        current_review = (0 <= last_render < last_position("review_visualization")
                          < last_position("publish_visualization")
                          and last_position("design_visualization") < last_render)
        review_ok = (review_ok is not False and bool(artifact) and approved_review(artifact)
                     and current_review)
    if expected.get("strict_source"):
        # Filled from the persisted full artifact in run_case (not a 50-row preview).
        source_fidelity_ok = False
        answer_fidelity_ok = answer_numbers_match(reply, artifact or {}, expected.get("message", ""))
    visible_columns_ok = (bool(artifact) and set(expected["visible_columns"]) <= visible_columns(artifact)
                          if "visible_columns" in expected else None)
    counts = Counter(part.tool_name for part in calls)
    repetition_ok = (all(counts[name] <= maximum for name, maximum in expected["max_tool_calls"].items())
                     if "max_tool_calls" in expected else None)
    reply_ok = (bool(reply) and all(re.search(pattern, reply, re.I) for pattern in expected["reply_patterns"])
                if "reply_patterns" in expected else None)
    if expected.get("forbid_questions") and (questioned or counts["ask_user"]):
        reply_ok = False
    axis_titles_ok = None
    if "axis_titles" in expected:
        try:
            spec = parse((artifact or {})["spec"])
            axes = expected["axis_titles"][spec.type]
            axis_titles_ok = all(text.casefold() in (getattr(spec, f"axis_{axis}_title") or "").casefold()
                                 for axis, text in axes.items())
        except (KeyError, TypeError, SpecError):
            axis_titles_ok = False
    labels_ok = None
    if "display_labels" in expected:
        try:
            spec = parse((artifact or {})["spec"])
            labels = expected["display_labels"]
            labels_ok = all(spec.column_labels.get(column) == label
                            for column, label in labels.get("column_labels", {}).items())
            labels_ok = labels_ok and all(spec.value_labels.get(column, {}).get(raw) == label
                                          for column, mapping in labels.get("value_labels", {}).items()
                                          for raw, label in mapping.items())
        except (KeyError, TypeError, SpecError):
            labels_ok = False
    semantic_ok, semantic_diagnostics = (semantic_fidelity(reply, artifact or {}, expected["semantic_fidelity"], brief)
        if "semantic_fidelity" in expected else (None, []))
    return {
        "tool": tool, "tool_ok": tool in accepted,
        "redo_ok": redo_ok,
        "outcome_ok": outcomes[expected["outcome"]],
        "observed_outcome": observed_outcome(value, last_tool),
        "fidelity_ok": fidelity_ok, "delivery_ok": delivery_ok,
        "answer_fidelity_ok": answer_fidelity_ok,
        "language_ok": language_ok,
        "source_fidelity_ok": source_fidelity_ok, "delegation_ok": delegation_ok, "chart_ok": chart_ok,
        "flow_ok": flow_ok,
        "binding_ok": binding_ok,
        "review_ok": review_ok,
        "render_evidence_ok": False if expected.get("require_render_evidence") else None,
        "visible_columns_ok": visible_columns_ok,
        "repetition_ok": repetition_ok,
        "reply_ok": bool(reply_ok) if reply_ok is not None else None,
        "axis_titles_ok": axis_titles_ok,
        "labels_ok": labels_ok,
        "semantic_fidelity_ok": semantic_ok,
        "semantic_diagnostics": semantic_diagnostics,
        "tools_called": [part.tool_name for part in calls],
        "tool_args": args, "tool_return": content,
        "tool_sequence": [{"name": c.tool_name, "id": c.tool_call_id, "args": c.args_as_dict()} for c in calls],
        "request_id": value.get("request_id"),
        "questioned": questioned,
        "artifact_id": artifact.get("artifact_id") if isinstance(artifact, dict) else None,
    }


def annotate_turns(record: dict) -> None:
    """Attach the last data call's saved revision and request usage to each turn."""
    requests = {request["request_id"]: request for request in record.get("requests", [])}
    for turn in record["turns"]:
        request = requests.get(turn["request_id"], {})
        turn["revised"] = (request.get("revision") or {}).get("problem")
        turn["requests_used"] = (turn.get("usage") or {}).get("requests", request.get("requests_used"))
        expected = turn["expected"]
        turn["revision_ok"] = ((turn["revised"] is not None) == expected["revision"]
                               if "revision" in expected else None)


def show_turn(name: str, index: int, turn: dict) -> None:
    redo = "" if turn["redo_ok"] is None else f" redo={turn['redo_ok']}"
    revision = "" if turn["revision_ok"] is None else f" revision={turn['revision_ok']}"
    error = f" error={turn['error']}" if turn.get("error") else ""
    print(f"{name} turn {index}: {turn['tool']} tool={turn['tool_ok']} "
          f"outcome={turn['outcome_ok']}{redo}{revision} revised={turn['revised']!r} "
          f"questioned={turn['questioned']} requests={turn['requests_used']} "
          f"seconds={turn.get('seconds', 0):.2f}{error}", flush=True)


def failed_score(error: str) -> dict:
    """Fail closed if evaluator code breaks, without discarding model evidence."""
    return {"tool": "none", "tool_ok": False, "outcome_ok": False,
            "observed_outcome": "evaluation_error", "redo_ok": None,
            "request_id": None, "artifact_id": None, "questioned": False,
            "tools_called": [], "tool_args": {}, "tool_return": None, "tool_sequence": [],
            "evaluation_error": error, "error": error}


def safe_score_turn(expected: dict, messages: list, reply: str | None = None, *,
                    brief: DataBrief | dict | None = None) -> dict:
    try:
        return score_turn(expected, messages, reply, **({"brief": brief} if brief is not None else {}))
    except Exception as exc:
        return failed_score(f"{type(exc).__name__}: {exc}")


async def run_case(case: dict, lead, profiler, analyst, designer, designer_fallback=None,
                   evidence_dir: Path | None = None, reviewer=None, turn_timeout: float = 120) -> dict:
    if not math.isfinite(turn_timeout) or turn_timeout <= 0:
        raise ValueError("turn_timeout must be a positive finite number")
    record = {"name": case["name"], "csv": case.get("csv", case.get("filename")),
              "heldout": case.get("heldout", False), "turn_timeout_seconds": turn_timeout, "turns": []}
    for key in ("evaluation_mode", "audit", "original_question"):
        if key in case:
            record[key] = case[key]
    with tempfile.TemporaryDirectory(prefix="vis-lead-eval-") as directory:
        try:
            store = DatasetStore(Path(directory))
            requests = RequestStore(store)
            deps = AppDeps(store, profiler, analyst, designer, requests, designer_fallback=designer_fallback,
                           reviewer=reviewer, lead=lead, caller_kind=case.get("caller_kind", "chat"),
                           caller_identity=case.get("caller_identity"))
            if "csv_text" in case:
                filename, content = case["filename"], case["csv_text"].encode("utf-8")
            else:
                csv = ROOT / case["csv"]
                filename, content = csv.name, csv.read_bytes()
            brief = None
            if isinstance(case.get("brief"), dict):
                brief = DataBrief.model_validate(case["brief"])
            elif case.get("brief"):
                brief = DataBrief.model_validate_json((ROOT / case["brief"]).read_bytes())
            uploaded = store.save_upload(filename, content, brief)
            record["dataset_id"] = uploaded.dataset_id
            record["source_csv_sha256"] = hashlib.sha256(content).hexdigest()
            store.import_csv(uploaded.dataset_id)
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            for expected in case["turns"]:
                turn = {**safe_score_turn(expected, []), "expected": expected, "reply": None,
                        "tool_ok": False, "outcome_ok": False,
                        "redo_ok": False if "redo_analysis" in expected else None, "error": record["error"]}
                record["turns"].append(turn)
            annotate_turns(record)
            for index, turn in enumerate(record["turns"], 1):
                show_turn(case["name"], index, turn)
            return record
        if any(turn.get("strict_source") for turn in case["turns"]):
            from vis_agent.analyst.source import load_csv_report
            try:
                original = load_csv_report(store, uploaded.dataset_id, case["turns"][0]["message"], brief=brief)
                record["source_signature"] = source_signature(original.result.columns, original.result.rows)
                record["source_warnings"] = original.warnings
            except Exception as exc:
                record["source_audit_error"] = f"{type(exc).__name__}: {exc}"
        history = []
        conversation_id = str(uuid4())
        for index, expected in enumerate(case["turns"], 1):
            started = perf_counter()
            prompt = expected["message"].replace("{dataset_id}", uploaded.dataset_id)
            reply, error = None, None
            usage = RunUsage()
            history_length = len(history)
            with capture_run_messages() as captured:
                try:
                    async with asyncio.timeout(turn_timeout):
                        result = await lead.run(prompt, deps=deps, message_history=history,
                                                conversation_id=conversation_id,
                                                usage=usage,
                                                usage_limits=UsageLimits(request_limit=REQUEST_LIMIT, tool_calls_limit=TOOL_LIMIT))
                    history = result.all_messages()
                    reply = result.output
                except TimeoutError:
                    error = f"TimeoutError: evaluation turn exceeded {turn_timeout:g}s wall-clock deadline"
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
            fresh = captured[history_length:]
            turn = {**safe_score_turn(expected, fresh, reply, brief=brief), "expected": expected, "message": prompt, "reply": reply,
                    "seconds": perf_counter() - started,
                    "usage": to_jsonable_python(usage),
                    "messages": json.loads(ModelMessagesTypeAdapter.dump_json(fresh))}
            if error:
                turn.update(error=error, outcome_ok=False)
            turn["latency_ok"] = turn["seconds"] <= expected["max_seconds"] if "max_seconds" in expected else None
            record["turns"].append(turn)
        # The temporary files disappear; retain the records and IDs for controller review.
        try:
            if evidence_dir is not None and (store.directory / "renders").exists():
                destination = evidence_dir / case["name"] / "renders"
                shutil.copytree(store.directory / "renders", destination, dirs_exist_ok=True)
                record["assets"] = [str(p.relative_to(evidence_dir)) for p in destination.rglob("*") if p.is_file()]
            record["requests"] = [requests.get_request(item.request_id).model_dump(mode="json")
                                  for item in requests.list_requests(dataset_id=uploaded.dataset_id)]
            record["artifacts"] = [requests.get_artifact(item.artifact_id).model_dump(mode="json")
                                   for item in requests.list_artifacts(dataset_id=uploaded.dataset_id)]
            by_id = {artifact["artifact_id"]: artifact for artifact in record["artifacts"]}
            for turn in record["turns"]:
                artifact = by_id.get(turn["artifact_id"], {})
                result_table = (artifact.get("report") or {}).get("result") or {}
                if turn["expected"].get("strict_source"):
                    actual = source_signature(result_table.get("columns", []), result_table.get("rows", []))
                    turn["source_fidelity_ok"] = bool(artifact) and actual == record.get("source_signature")
                    turn["artifact_source_signature"] = actual
                    # The lead sees at most LEAD_ROWS, but an answer may cite any
                    # verified value in the complete delivered table.
                    public = ((turn.get("tool_return") or {}).get("artifact") or {}).copy()
                    public["rows"] = result_table.get("rows", [])
                    turn["answer_fidelity_ok"] = answer_numbers_match(turn["reply"], public, turn["expected"]["message"])
                    if "semantic_fidelity" in turn["expected"]:
                        turn["semantic_fidelity_ok"], turn["semantic_diagnostics"] = semantic_fidelity(
                            turn["reply"], public, turn["expected"]["semantic_fidelity"], brief)
                if turn["expected"].get("require_render_evidence"):
                    url = artifact.get("png_url") or ""
                    candidate = store.directory / url.lstrip("/")
                    render_root = (store.directory / "renders").resolve()
                    safe = candidate.resolve().is_relative_to(render_root)
                    content = candidate.read_bytes() if safe and candidate.is_file() else b""
                    valid = content.startswith(b"\x89PNG\r\n\x1a\n") and len(content) >= 24
                    width = int.from_bytes(content[16:20], "big") if valid else 0
                    height = int.from_bytes(content[20:24], "big") if valid else 0
                    turn["render_evidence_ok"] = valid and width > 0 and height > 0
                    turn["render_evidence"] = ({"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content),
                                                "width": width, "height": height, "url": url}
                                               if turn["render_evidence_ok"] else None)
                if "analysis_reused" in turn["expected"]:
                    parent = by_id.get(artifact.get("parent_artifact_id"), {})
                    left, right = artifact.get("report", {}), parent.get("report", {})
                    # A language-only revision changes report.language while reusing all saved SQL work.
                    same = bool(parent) and all(left.get(key) == right.get(key) for key in (
                        "analysis", "result", "created_at", "model", "seconds"))
                    turn["analysis_reuse_ok"] = bool(parent) and same == turn["expected"]["analysis_reused"]
            record["stage_reports"] = [
                {"request_id": request["request_id"], "stage": stage, "round": round_number,
                 **{key: report.get(key) for key in ("seconds", "requests", "model", "status") if key in report}}
                for request in record["requests"]
                for round_number, steps in enumerate([*request.get("rounds", []), request.get("steps", {})], 1)
                for stage, report in steps.items() if isinstance(report, dict) and "seconds" in report
            ]
        except Exception as exc:  # one case's records must not abort the others
            record["records_error"] = f"{type(exc).__name__}: {exc}"
            for turn in record["turns"]:
                turn.update(outcome_ok=False, evaluation_error=record["records_error"])
        annotate_turns(record)
        for index, turn in enumerate(record["turns"], 1):
            show_turn(case["name"], index, turn)
    return record


def summarize(results: list[dict]) -> dict:
    """Report repair decisions and indicator fidelity, including held-out cases separately."""
    turns = [turn for case in results for turn in case["turns"]]
    fidelity_keys = FIDELITY_KEYS
    passed = [all(t["tool_ok"] and t["outcome_ok"]
                  and all(t.get(key) is not False for key in ("redo_ok", "revision_ok", *fidelity_keys))
                  for t in case["turns"]) for case in results]
    summary = {"cases": len(results), "cases_ok": sum(passed),
               "turns": len(turns), "tool_ok": sum(t["tool_ok"] for t in turns),
               "outcome_ok": sum(t["outcome_ok"] for t in turns),
               "redo_turns": sum(t["redo_ok"] is not None for t in turns),
               "redo_ok": sum(t["redo_ok"] is True for t in turns),
               "revision_turns": sum(t["revision_ok"] is not None for t in turns),
               "revision_ok": sum(t["revision_ok"] is True for t in turns),
               "revisions": sum(t["revised"] is not None for t in turns),
               "false_questions": sum(t["expected"]["outcome"] == "chart" and t["questioned"] for t in turns),
               "requests": sum(t["requests_used"] or 0 for t in turns),
               "usage_missing_turns": sum(t["requests_used"] is None for t in turns),
               "heldout_cases": sum(bool(case.get("heldout")) for case in results),
               "heldout_cases_ok": sum(ok for case, ok in zip(results, passed) if case.get("heldout"))}
    for key in fidelity_keys:
        checked = [t[key] for t in turns if t.get(key) is not None]
        summary[key] = {"passed": sum(checked), "checked": len(checked)}
    summary["observed_outcomes"] = {name: sum(t.get("observed_outcome") == name for t in turns)
        for name in sorted({t["observed_outcome"] for t in turns if t.get("observed_outcome")})}
    seconds = [t["seconds"] for t in turns if "seconds" in t]
    def percentile(values: list[float], quantile: float) -> float:
        ordered = sorted(values)
        index = (len(ordered) - 1) * quantile
        lower = math.floor(index)
        return ordered[lower] + (ordered[math.ceil(index)] - ordered[lower]) * (index - lower)
    summary["latency_seconds"] = ({"mean": sum(seconds) / len(seconds), "max": max(seconds),
                                   "p50": percentile(seconds, .5), "p90": percentile(seconds, .9),
                                   "p95": percentile(seconds, .95)} if seconds else None)
    strict = [t for t in turns if t["expected"].get("require_render_evidence")]
    if strict:
        # A visual inspector pass is evidence, not a mathematical guarantee of
        # aesthetics. Keep chart/table success separate from graceful limitations.
        verified = [t for t in strict if t["tool_ok"] and t["outcome_ok"] and all(
            t.get(key) is not False for key in fidelity_keys if key != "latency_ok")]
        chart_type = lambda t: (((t.get("tool_return") or {}).get("artifact") or {}).get("chart"))
        summary["verified_charts"] = sum(chart_type(t) != "table" for t in verified)
        summary["verified_rendered_tables"] = sum(chart_type(t) == "table" for t in verified)
        summary["rendered_cases_required"] = len(strict)
    dispositions = sorted({t["expected"]["disposition"] for t in turns if "disposition" in t["expected"]})
    if dispositions:
        summary["dispositions"] = {name: {"cases": sum(any(t["expected"].get("disposition") == name for t in c["turns"]) for c in results),
                                                 "passed": sum(ok for c, ok in zip(results, passed)
                                                               if any(t["expected"].get("disposition") == name for t in c["turns"]))}
                                   for name in dispositions}
    print(f"cases {summary['cases_ok']}/{summary['cases']}, tool choice {summary['tool_ok']}/{summary['turns']}, "
          f"outcome {summary['outcome_ok']}/{summary['turns']}, "
          f"redo analysis {summary['redo_ok']}/{summary['redo_turns']}, "
          f"revision expected {summary['revision_ok']}/{summary['revision_turns']}, "
          f"revisions: {summary['revisions']}, false questions: {summary['false_questions']}, "
          f"requests: {summary['requests']}")
    print(f"held-out cases {summary['heldout_cases_ok']}/{summary['heldout_cases']}")
    checked_metrics = [f"{key} {summary[key]['passed']}/{summary[key]['checked']}"
                       for key in fidelity_keys if summary[key]["checked"]]
    if checked_metrics:
        print(", ".join(checked_metrics))
    return summary


def use_instructions(path: Path) -> str:
    """Run the lead with candidate instructions (an optimizer's output) instead of the source's, for this process."""
    text = path.read_text(encoding="utf-8")
    vis_agent.lead.LEAD_INSTRUCTIONS = text
    return text


def code_paths() -> tuple[list[Path], list[Path]]:
    """Keep application changes distinguishable from evaluator-only changes."""
    application = [p for p in (ROOT / "vis_agent").rglob("*") if p.is_file()
                   and "node_modules" not in p.parts and "__pycache__" not in p.parts
                   and p.suffix in {".py", ".md", ".js", ".mjs", ".ts", ".json"}]
    evaluation = [ROOT / "evals/lead/run.py", ROOT / "evals/lead/dev20.py",
                  ROOT / "evals/lead/dev20-expectations.json", ROOT / "evals/lead/dev20-additional.json"]
    return application, evaluation


def code_fingerprint(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def runtime_fingerprint() -> str:
    """Legacy combined hash, retained for comparison with earlier saved runs."""
    application, evaluation = code_paths()
    return code_fingerprint(application + evaluation)


def save_checkpoint(record: dict, evidence_dir: Path) -> None:
    """Persist each completed case before aggregate scoring can fail."""
    directory = evidence_dir / record["name"]
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / "case.json.tmp"
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(directory / "case.json")


async def evaluate(cases: list[dict], evidence_dir: Path | None = None, concurrency: int = 3,
                   turn_timeout: float = 120) -> dict:
    # Use exactly the application's provider, model settings, and optional specialists.
    if concurrency < 1:
        raise ValueError("concurrency must be at least one")
    if not math.isfinite(turn_timeout) or turn_timeout <= 0:
        raise ValueError("turn_timeout must be a positive finite number")
    fingerprint = runtime_fingerprint()
    application_paths, evaluation_paths = code_paths()
    application_hash, evaluation_hash = code_fingerprint(application_paths), code_fingerprint(evaluation_paths)
    cases_hash = hashlib.sha256(json.dumps(cases, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="vis-lead-eval-config-") as directory:
        store = DatasetStore(Path(directory))
        team = teams_from_env(store, RequestStore(store))[0]
        agents = {"lead": team.lead, "profiler": team.deps.profiler, "analyst": team.deps.analyst,
                  "designer": team.deps.designer, "designer_fallback": team.deps.designer_fallback,
                  "reviewer": team.deps.reviewer}
        models = {name: agent.model if isinstance(agent.model, str) else agent.model.model_id
                  for name, agent in agents.items() if agent is not None and agent.model is not None}
        semaphore = asyncio.Semaphore(concurrency)
        run_configuration = {"models": models, "provider": team.label, "concurrency": concurrency,
                             "turn_timeout_seconds": turn_timeout, "runtime_code_sha256": fingerprint,
                             "application_code_sha256": application_hash, "evaluation_code_sha256": evaluation_hash,
                             "evaluation_cases_sha256": cases_hash,
                             "lead_instructions_sha256": hashlib.sha256(vis_agent.lead.LEAD_INSTRUCTIONS.encode()).hexdigest()}

        async def bounded(case):
            async with semaphore:
                try:
                    record = await run_case(case, team.lead, team.deps.profiler, team.deps.analyst,
                                            team.deps.designer, team.deps.designer_fallback, evidence_dir,
                                            team.deps.reviewer, turn_timeout=turn_timeout)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    record = {"name": case["name"], "csv": case.get("csv", case.get("filename")),
                              "heldout": case.get("heldout", False), "evaluation_error": error,
                              "turns": [{**failed_score(error), "expected": turn, "reply": None}
                                        for turn in case["turns"]]}
                    annotate_turns(record)
                record["run_configuration"] = run_configuration
                if evidence_dir is not None:
                    save_checkpoint(record, evidence_dir)
                return record

        results = await asyncio.gather(*(bounded(case) for case in cases))
    summary = summarize(results)
    current_application, current_evaluation = code_paths()
    return {**run_configuration, "model": models["lead"], "summary": summary, "cases": results,
            "runtime_changed_during_run": fingerprint != runtime_fingerprint(),
            "application_changed_during_run": application_hash != code_fingerprint(current_application),
            "evaluation_changed_during_run": evaluation_hash != code_fingerprint(current_evaluation)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", action="store_true", help="Append cases sampled from the development CSV corpus.")
    parser.add_argument("--corpus-count", type=int, default=10,
                        help="Number of development-corpus cases to append (default: 10).")
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("cases.json"))
    parser.add_argument("--dev20", choices=("original", "handoff", "renderable"),
                        help="Append audited original/handoff twenty, or the separate renderer-supported twenty.")
    parser.add_argument("--concurrency", type=int, default=3, help="Maximum simultaneous cases (default: 3).")
    parser.add_argument("--turn-timeout", type=float, default=120,
                        help="Fail a turn after this wall-clock deadline; separate from the pass SLA (default: 120s).")
    parser.add_argument("--out", type=Path, default=Path("results.json"), help="Write results here (default: results.json).")
    parser.add_argument("--only", metavar="NAME", help="Run only this named case.")
    parser.add_argument("--instructions", type=Path, metavar="PATH",
                        help="Run the lead with these instructions instead of the source's (an optimizer's output).")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    cases = load_cases(args.cases)
    if args.corpus:
        cases += corpus_cases(count=args.corpus_count)
    if args.dev20:
        from evals.lead.dev20 import cases as dev20_cases
        cases += dev20_cases(args.dev20)
    if args.concurrency < 1:
        parser.error("--concurrency must be at least one")
    if not math.isfinite(args.turn_timeout) or args.turn_timeout <= 0:
        parser.error("--turn-timeout must be a positive finite number")
    if args.instructions:
        use_instructions(args.instructions)
    if args.only:
        cases = [case for case in cases if case["name"] == args.only]
        if not cases:
            parser.error(f"Unknown case: {args.only}")
    results = asyncio.run(evaluate(cases, args.out.parent / (args.out.stem + "-assets"), args.concurrency,
                                   args.turn_timeout))
    from evals.evidence import provenance
    results["provenance"] = provenance(args.cases, results["models"])
    results["provenance"]["prompts"]["lead"] = vis_agent.lead.LEAD_INSTRUCTIONS
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if results["summary"]["cases_ok"] != results["summary"]["cases"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
