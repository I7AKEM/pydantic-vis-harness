"""Build twenty reproducible Hijri and Arabic cases from a read-only CSV corpus."""

import argparse
import csv
from datetime import date as Date, datetime
import json
from pathlib import Path
import random
import re

import duckdb
from hijridate import Gregorian


HIJRI_MONTHS_AR = [
    "محرم", "صفر", "ربيع الأول", "ربيع الآخر", "جمادى الأولى", "جمادى الآخرة",
    "رجب", "شعبان", "رمضان", "شوال", "ذو القعدة", "ذو الحجة",
]
CORPUS = Path("/Users/muhammad/Documents/NACI/Insightor/insightor_POC/exports/"
              "visualization_csv_corpus_dev_2026-09-01_500")
OUT = Path(__file__).resolve().parents[1] / "scale" / "seeded"
ARABIC = re.compile("[ء-ي]")
DIGITS = str.maketrans("0123456789,.", "٠١٢٣٤٥٦٧٨٩٬٫")
NUMBER = r"[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?"


def _hijri(date: str):
    value = Date.fromisoformat(date)
    return Gregorian(value.year, value.month, value.day).to_hijri()


def to_hijri_iso(date: str) -> str:
    return _hijri(date).isoformat()


def to_hijri_arabic_digits(date: str) -> str:
    return arabic_digits(to_hijri_iso(date).replace("-", "/"))


def to_hijri_month_name(date: str) -> str:
    value = _hijri(date)
    return f"{value.day} {HIJRI_MONTHS_AR[value.month - 1]} {value.year}"


def arabic_digits(text: str) -> str:
    return text.translate(DIGITS)


def _identifier(column: str) -> str:
    return '"' + column.replace('"', '""') + '"'


def _candidates(corpus: Path) -> list[dict]:
    entries = [json.loads(line) for line in (corpus / "manifest.jsonl").read_text(
        encoding="utf-8").splitlines() if line.strip()]
    candidates = []
    with duckdb.connect() as db:
        for entry in sorted(entries, key=lambda item: item["dataset_id"]):
            fingerprint = entry["fingerprint"]
            profile = fingerprint["data_profile"]
            if (fingerprint.get("parse_status", "parsed") != "parsed"
                    or profile.get("geometry_columns") or profile.get("very_large_cell_count", 0)):
                continue
            path = (corpus / entry["csv_path"]).resolve()
            if not path.is_relative_to((corpus / "csv").resolve()):
                raise ValueError(f"CSV is outside corpus/csv: {entry['csv_path']}")
            with path.open(encoding="utf-8-sig", newline="") as stream:
                columns = next(csv.reader(stream))
            if any(re.search(r"geometry|geom|wkt", column, re.I) for column in columns):
                continue
            db.execute("CREATE OR REPLACE TEMP TABLE source AS SELECT * FROM "
                       "read_csv(?, header=true, all_varchar=true)", [str(path)])
            temporal = None
            for column in profile.get("temporal_columns", []):
                if column not in columns:
                    continue
                value = _identifier(column)
                months, invalid, earliest, latest = db.execute(f"""
                    SELECT count(DISTINCT date_trunc('month', try_cast({value} AS DATE))),
                           count(*) FILTER (WHERE nullif(trim({value}), '') IS NOT NULL AND
                               (NOT regexp_matches({value}, '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}($|[ T])')
                                OR try_cast({value} AS DATE) IS NULL)),
                           min(try_cast({value} AS DATE)), max(try_cast({value} AS DATE))
                    FROM source
                """).fetchone()
                if months < 12 or invalid:
                    continue
                try:
                    to_hijri_iso(earliest.isoformat())
                    to_hijri_iso(latest.isoformat())
                except (ValueError, OverflowError):
                    continue
                temporal = column
                break
            occurrences = entry.get("occurrences") or [{}]
            intent = occurrences[0].get("orchestrator_intent") or {}
            declared = [item["field"] for item in intent.get("measures", []) if item.get("field")]
            dimensions = intent.get("dimensions", [])
            measure = None
            category = None
            for column in dict.fromkeys(declared + columns):
                if column not in columns:
                    continue
                value = _identifier(column)
                numeric, invalid, arabic = db.execute(f"""
                    SELECT count(*) FILTER (WHERE regexp_full_match(trim({value}), ?)),
                           count(*) FILTER (WHERE nullif(trim({value}), '') IS NOT NULL
                               AND NOT regexp_full_match(trim({value}), ?)),
                           count(*) FILTER (WHERE regexp_matches({value}, '[ء-ي]'))
                    FROM source
                """, [NUMBER, NUMBER]).fetchone()
                identifier = re.search(r"(^|_)(id|year|month|latitude|longitude)(_|$)|number$", column, re.I)
                if (measure is None and numeric and not invalid and column != temporal
                        and column not in dimensions and not identifier):
                    measure = column
                if category is None and arabic and profile.get("arabic_cell_count", 0):
                    category = column
            if measure is not None:
                candidates.append({"dataset_id": entry["dataset_id"], "path": path,
                                   "temporal": temporal, "measure": measure, "category": category})
    return candidates


def _category(text: str, style: str) -> str:
    if not text.strip() or not ARABIC.search(text):
        return text
    if style == "diacritics":
        return ARABIC.sub(lambda match: match[0] + "َ", text)
    if style == "tatweel":
        return ARABIC.sub(lambda match: match[0] + "ـ", text, count=1)
    if style == "mixed_direction":
        return text + " (Riyadh)"
    if style == "arabic_digits":
        # Keep existing numbered labels; add a synthetic marker if they lack digits.
        return arabic_digits(text if re.search("[0-9]", text) else text + " (1)")
    return text + " — تسمية عربية مطولة لاختبار وضوح عرض الفئات في الرسم البياني"


def seed(corpus: Path, out: Path, seed: int = 7) -> list[dict]:
    corpus, out = Path(corpus).resolve(), Path(out).resolve()
    if out == corpus or out.is_relative_to(corpus):
        raise ValueError("Output must be outside the read-only corpus")
    candidates = _candidates(corpus)
    rng = random.Random(seed)
    rng.shuffle(candidates)
    temporal = [item for item in candidates if item["temporal"]]
    categories = [item for item in candidates if item["category"]]
    for label, pool in (("temporal", temporal), ("measure", candidates), ("Arabic category", categories)):
        if not pool:
            raise ValueError(f"No eligible {label} source in corpus")

    plans = []
    for index in range(8):
        # Offset each pass so a small pool also exercises different written forms per source.
        source = temporal[(index + index // len(temporal)) % len(temporal)]
        plans.append((source, {"kind": "hijri_date", "column": source["temporal"],
                              "format": ("iso", "arabic_digits", "month_name")[index % 3],
                              "bucket": "month" if index % 2 == 0 else "year"}))
    for index in range(4):
        source = categories[index % len(categories)]
        plans.append((source, {"kind": "arabic_digits", "column": source["measure"]}))
    for index, style in enumerate(("diacritics", "tatweel", "mixed_direction", "arabic_digits",
                                   "long_label", "long_label")):
        source = categories[index % len(categories)]
        plans.append((source, {"kind": "arabic_categories", "column": source["category"], "style": style}))
    for index in range(2):
        source = temporal[index % len(temporal)]
        plans.append((source, {"kind": "hijri_year", "column": source["temporal"],
                              "added_column": "hijri_year", "bucket": "year"}))

    out.mkdir(parents=True, exist_ok=True)
    cases = []
    converters = {"iso": to_hijri_iso, "arabic_digits": to_hijri_arabic_digits,
                  "month_name": to_hijri_month_name}
    for index, (source, transformation) in enumerate(plans, start=1):
        kind, column = transformation["kind"], transformation["column"]
        name = f"seeded-{index:02d}-{kind.replace('_', '-')}"
        with source["path"].open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = list(reader.fieldnames)
            rows = list(reader)
        if kind == "hijri_year":
            added = transformation["added_column"]
            while added in fields:
                added += "_seeded"
            transformation["added_column"] = added
            fields.append(added)
        for row in rows:
            value = row[column]
            if kind in {"hijri_date", "hijri_year"}:
                # Use the date as written, with no timezone shift; discard time only in the target column.
                gregorian = datetime.fromisoformat(value.strip()).date().isoformat() if value.strip() else None
                if kind == "hijri_year":
                    row[transformation["added_column"]] = to_hijri_iso(gregorian)[:4] if gregorian else value
                elif gregorian:
                    row[column] = converters[transformation["format"]](gregorian)
            elif kind == "arabic_digits":
                row[column] = arabic_digits(value)
            else:
                row[column] = _category(value, transformation["style"])
        with (out / f"{name}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        if kind in {"hijri_date", "hijri_year"}:
            bucket = "الأشهر الهجرية" if transformation["bucket"] == "month" else "السنوات الهجرية"
            time_column = transformation.get("added_column", column)
            question = f'اعرض متوسط «{source["measure"]}» حسب {bucket} باستخدام «{time_column}».'
            intent = "trend"
        else:
            category = source["category"] or source["temporal"]
            question = f'اعرض قيم «{source["measure"]}»'
            question += f' حسب «{category}».' if category else " وقارن بينها."
            intent = "compare"
        cases.append({"name": name, "csv": f"{name}.csv", "source_dataset_id": source["dataset_id"],
                      "transformation": transformation, "question": question, "language": "ar",
                      "intent": intent, "expect": "design", "seeded": True})
    (out / "seeded.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    cases = seed(args.corpus, args.out, args.seed)
    print(f"Wrote {len(cases)} seeded cases to {args.out}")


if __name__ == "__main__":
    main()
