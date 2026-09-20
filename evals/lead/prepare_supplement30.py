"""Freeze a coverage-first, seeded 30-case extension without modifying the running evaluator.

No network calls or source-data writes. The initial twenty remain segment one;
this module produces segment two for both model arms, before any segment-two call.
"""

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone

from evals.designer.agent.corpus_tools.select import CORPUS, read_manifest, select
from evals.lead.dev20 import cases as initial_cases
from evals.lead.run import code_fingerprint, code_paths
from vis_agent.analyst.source import SOURCE_ROW_CAP
from vis_agent.designer.resolve import MAX_TABLE_HEIGHT, TABLE_HEADER_AND_FRAME_HEIGHT, TABLE_ROW_HEIGHT
from vis_agent.profiler.measurements import GEOMETRY_NAME

SEED = 20260917
PERSONAL_COLUMN = re.compile(
    r"violator_id|person_id|resident_id|national_id|identity|passport|phone|mobile|email|plate|"
    r"control_number|sequence_number", re.I,
)


def numeric(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def prepare() -> dict:
    manifest = read_manifest(CORPUS / "manifest.jsonl")
    originals = initial_cases("renderable")
    original_ids = {case["name"].removeprefix("corpus-") for case in originals}
    original_hashes = {row["fingerprint"].get("canonical_table_sha256")
                       for row in manifest if row["dataset_id"] in original_ids}
    original_hashes.discard(None)
    seen_hashes = set(original_hashes)
    eligible, excluded = [], []
    for row in sorted(manifest, key=lambda entry: entry["dataset_id"]):
        fingerprint = row.get("fingerprint") or {}
        columns = fingerprint.get("parsed_columns", [])
        canonical = fingerprint.get("canonical_table_sha256")
        reason = None
        if row["dataset_id"] in original_ids:
            reason = "initial20"
        elif any(PERSONAL_COLUMN.search(column) for column in columns):
            reason = "individual-record identifiers: aggregate/non-identifying corpus preferred"
        elif canonical and canonical in seen_hashes:
            reason = "duplicate canonical table"
        if reason:
            excluded.append({"id": row["dataset_id"], "reason": reason})
            continue
        if canonical:
            seen_hashes.add(canonical)
        eligible.append(row)
    chosen = select(eligible, CORPUS, count=30, seed=SEED)
    assert len(chosen) == 30
    built = []
    frozen_sources = []
    for entry in chosen:
        path = CORPUS / "csv" / (entry["dataset_id"] + ".csv")
        assert str(path) == entry["csv"]
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source)
            columns = next(reader)
            records = list(reader)
        available = [name for name in columns if not GEOMETRY_NAME.search(name)]
        features = entry["features"]
        limited = features["rows"] > SOURCE_ROW_CAP
        category_only = all(not any(numeric(row[columns.index(name)]) for row in records)
                            for name in available)
        table_limit = (MAX_TABLE_HEIGHT - TABLE_HEADER_AND_FRAME_HEIGHT) // TABLE_ROW_HEIGHT
        table_boundary = not limited and category_only and features["rows"] > table_limit
        field_list = ", ".join(available)
        message = (
            "أنا وكيل البيانات؛ الملف المرفق نتيجة نهائية معتمدة. قدّم عرضاً واضحاً للقيم والحقول "
            f"التالية كما وردت: {field_list}. "
            "اختر الرسم المناسب أو جدولاً عندما تتعدد الوحدات أو تكون النتيجة نصية. "
            "يجب تمثيل الحقول المذكورة بوضوح دون تغيير خلايا المصدر أو إعادة حساب المقاييس. "
            "احتفظ بالقيم المفقودة كمفقودة ولا تستبدلها بصفر؛ لا تعِد تجميع الصفوف أو تأخذ عينة. "
            "احتفظ بالرموز الأصلية دون اختراع معاني لها، ولا تفترض عملة أو وحدة غير مذكورة. "
            "أجب بالعربية، واترك القيم والأسماء الأصلية دون تحريف."
        )
        if limited:
            message += (
                " إذا تجاوز الملف الحد التقني للمحرك، اشرح الحد بوضوح دون إنشاء رسم جزئي مضلل "
                "ودون طلب بيانات جديدة أو إعادة المحاولة على نفس المصدر."
            )
        elif table_boundary:
            message += (
                " لا توجد قيمة كمية مطلوبة هنا: حافظ على كل صفوف النص ولا تحول تكرار الأسماء إلى أعداد. "
                "يكفي تسليم الجدول المصدر الكامل إذا لم يتسع في صورة ثابتة؛ وضح أنه جدول وليس رسماً محققاً. "
                "لا تعتبر قص نافذة جدول قابلة للتمرير عيباً ما دامت كل صفوفه متاحة."
            )
        elif features["temporal"]:
            message += " حافظ على هوية الفترات والتواريخ الأصلية وترتيبها؛ لا تعِد حساب معدلات النمو."
        elif features["long_text"]:
            message += " اجعل التسميات الطويلة مقروءة مع الحفاظ على هوية الفئات."
        units = {name: "%" for name in available
                 if re.search(r"percentage|_pct$|percent|بالمائه|بالمئة", name, re.I)}
        if units:
            message += " الحقول المئوية جاهزة بوحدة %، فلا تضربها في مئة أو تعِد حسابها."
        message_with_link = message + f"\n\nAttached CSV: [{path.name}](/datasets/{{dataset_id}}/profile)"
        turn = {
            "message": message_with_link,
            "tool": "draw",
            "outcome": "handled" if limited else "fallback" if table_boundary else "artifact",
            "disposition": "unsupported" if limited else "table_fallback" if table_boundary else "chart",
            "forbid_questions": True,
            "max_seconds": 60,
            "max_tool_calls": {"draw": 1, "design_visualization": 0 if limited else 2,
                               "render_visualization": 0 if limited else 2,
                               "review_visualization": 0 if limited else 2,
                               "publish_visualization": 1, "profile_csv": 0, "consult_analyst": 0},
        }
        if limited:
            turn.update(no_image=True, reply_patterns=[
                "حد|يسمح|يدعم|تجاوز|limit|exceed|maximum|support",
                "10[٬,، ]?000|١٠[٬,، ]?٠٠٠|عشرة آلاف|عشرة الاف|ten thousand",
            ])
        elif table_boundary:
            turn.update(strict_source=True, no_image=True,
                        reply_patterns=["جدول|table", "كامل|جميع|صف|الصفوف|full|all|rows"])
        else:
            turn.update(strict_source=True, require_delivery=True, require_render_evidence=True,
                        review_required=True, review_pass_required=True, prepared_csv=True,
                        visible_columns=available)
        built.append({
            "name": "corpus-" + entry["dataset_id"], "csv": str(path), "turns": [turn],
            "evaluation_mode": "supplement30-prepared-handoff",
            "audit": "Coverage-first then seeded selection; original question is provenance, not the new task.",
            "original_question": entry["question"], "coverage": features,
            "brief": {"producer_agent": "data-agent", "raw_question": message, "units": units,
                      "caveats": ["Authoritative prepared CSV; no recomputation or invented code meanings."]},
            "caller_kind": "agent", "caller_identity": "eval-data-agent",
        })
        frozen_sources.append({"id": entry["dataset_id"], "csv_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                               "columns": columns, "features": features,
                               "expected_boundary": "source_limit" if limited else "table_source_fallback" if table_boundary else None})
    assert len({case["name"] for case in originals + built}) == 50
    application, evaluator = code_paths()
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(), "seed": SEED,
        "selection": "Existing coverage-first selector then seeded shuffle; model outcomes were not used.",
        "cohort": "Initial frozen renderable20 + distinct frozen supplement30; never a held-out set.",
        "cases_sha256": hashlib.sha256(json.dumps(built, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        "application_sha256": code_fingerprint(application), "evaluator_sha256": code_fingerprint(evaluator),
        "case_count": 30, "combined_count": 50,
        "rendered_presentations": sum(not row["expected_boundary"] for row in frozen_sources),
        "technical_boundaries": sum(bool(row["expected_boundary"]) for row in frozen_sources),
        "coverage": {key: dict(Counter(str(row["features"][key]) for row in frozen_sources))
                     for key in ("shape", "rows_bucket", "temporal", "nulls", "negatives", "long_text")},
        "sources": frozen_sources, "exclusions": excluded,
        "scroll_contract": "Viewport cropping is not inherently a defect. Static-image coverage and complete accessible HTML/table are audited separately; an expected boundary is not a chart pass.",
    }
    return {"cases": built, "manifest": metadata}


if __name__ == "__main__":
    print(json.dumps(prepare(), ensure_ascii=False, indent=2))
