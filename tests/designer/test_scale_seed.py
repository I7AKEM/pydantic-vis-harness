import csv
import json

import duckdb
import pytest
from hijridate import Hijri

from evals.designer.agent.corpus_tools.seed import (
    HIJRI_MONTHS_AR, arabic_digits, seed, to_hijri_arabic_digits,
    to_hijri_iso, to_hijri_month_name,
)


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "corpus"
    (root / "csv").mkdir(parents=True)
    manifest = []
    for index in range(3):
        name = f"source-{index}"
        with (root / "csv" / f"{name}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(['date', 'measure', 'category', 'unchanged'])
            for month in range(1, 13):
                writer.writerow([f"2024-{month:02d}-11", "-1,234.50", f"الرياض {month}", '001, "keep"\nنص'])
            writer.writerow(["", "", "", "NULL"])
        manifest.append({
            "dataset_id": name, "csv_path": f"csv/{name}.csv",
            "fingerprint": {"parse_status": "parsed", "data_profile": {
                "temporal_columns": ["date"], "arabic_cell_count": 12,
                "geometry_columns": [], "very_large_cell_count": 0,
            }},
            "occurrences": [{"orchestrator_intent": {
                "measures": [{"field": "measure"}], "dimensions": ["category"],
            }}],
        })
    (root / "manifest.jsonl").write_text(
        "\n".join(json.dumps(entry) for entry in manifest), encoding="utf-8",
    )
    return root


def test_known_conversions():
    assert to_hijri_iso("2024-03-11") == "1445-09-01"
    assert to_hijri_arabic_digits("2024-03-11") == "١٤٤٥/٠٩/٠١"
    assert to_hijri_month_name("2024-03-11") == "1 رمضان 1445"
    assert arabic_digits("1,234.5") == "١٬٢٣٤٫٥"
    assert arabic_digits("-001.50% الرياض 2") == "-٠٠١٫٥٠% الرياض ٢"


@pytest.mark.parametrize("month", range(1, 13))
def test_all_month_names(month):
    date = Hijri(1445, month, 1).to_gregorian().isoformat()
    assert to_hijri_month_name(date) == f"1 {HIJRI_MONTHS_AR[month - 1]} 1445"


@pytest.mark.parametrize("date", ["2024-02-30", "2024-03", "1900-01-01"])
def test_invalid_or_unsupported_dates(date):
    with pytest.raises((ValueError, OverflowError)):
        to_hijri_iso(date)


def test_seed_preserves_cells_and_records_transformations(corpus, tmp_path):
    out = tmp_path / "seeded"
    cases = seed(corpus, out)
    assert json.loads((out / "seeded.json").read_text()) == cases
    assert len(cases) == 20
    assert len({case["name"] for case in cases}) == 20
    kinds = [case["transformation"]["kind"] for case in cases]
    assert {kind: kinds.count(kind) for kind in set(kinds)} == {
        "hijri_date": 8, "arabic_digits": 4, "arabic_categories": 6, "hijri_year": 2,
    }
    forms = []
    styles = []
    for case in cases:
        assert case["language"] == "ar" and case["expect"] == "design" and case["seeded"] is True
        assert case["intent"] in {"trend", "compare"}
        assert "charts" not in case
        fields, source = read_csv(corpus / "csv" / f'{case["source_dataset_id"]}.csv')
        output_fields, rows = read_csv(out / case["csv"])
        assert len(source) == len(rows)
        transform = case["transformation"]
        column = transform["column"]
        kind = transform["kind"]
        assert output_fields == fields + ([transform["added_column"]] if kind == "hijri_year" else [])
        for before, after in zip(source, rows, strict=True):
            for field in fields:
                if field != column or kind == "hijri_year":
                    assert before[field] == after[field]
            if not before[column]:
                assert after[transform.get("added_column", column)] == ""
                continue
            if kind == "hijri_date":
                convert = {"iso": to_hijri_iso, "arabic_digits": to_hijri_arabic_digits,
                           "month_name": to_hijri_month_name}[transform["format"]]
                assert after[column] == convert(before[column])
                assert "الهجرية" in case["question"]
            elif kind == "hijri_year":
                assert after[transform["added_column"]] == to_hijri_iso(before[column])[:4]
            elif kind == "arabic_digits":
                assert after[column] == arabic_digits(before[column])
            else:
                style = transform["style"]
                assert after[column] != before[column]
                if style == "diacritics":
                    assert "َ" in after[column]
                elif style == "tatweel":
                    assert "ـ" in after[column]
                elif style == "mixed_direction":
                    assert after[column].endswith(" (Riyadh)")
                elif style == "arabic_digits":
                    assert "١" in after[column] or "٢" in after[column] or arabic_digits(before[column]) == after[column]
                else:
                    with duckdb.connect() as db:
                        assert db.execute("SELECT length(?) > 40", [after[column]]).fetchone()[0]
        if kind == "hijri_date":
            forms.append(transform["format"])
        if kind == "arabic_categories":
            styles.append(transform["style"])
    assert forms == ["iso", "arabic_digits", "month_name"] * 2 + ["iso", "arabic_digits"]
    assert len({(case["source_dataset_id"], case["transformation"]["format"])
                for case in cases if case["transformation"]["kind"] == "hijri_date"}) == 8
    assert styles == ["diacritics", "tatweel", "mixed_direction", "arabic_digits", "long_label", "long_label"]


def test_seed_is_byte_deterministic_even_with_reordered_manifest(corpus, tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    seed(corpus, first)
    manifest = corpus / "manifest.jsonl"
    manifest.write_text("\n".join(reversed(manifest.read_text().splitlines())))
    seed(corpus, second)
    assert {p.name: p.read_bytes() for p in first.iterdir()} == {
        p.name: p.read_bytes() for p in second.iterdir()
    }
    seed(corpus, first)
    assert {p.name: p.read_bytes() for p in first.iterdir()} == {
        p.name: p.read_bytes() for p in second.iterdir()
    }


def test_insufficient_months_fails_before_writing(corpus, tmp_path):
    for path in (corpus / "csv").glob("*.csv"):
        fields, rows = read_csv(path)
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows[:11])
    out = tmp_path / "seeded"
    with pytest.raises(ValueError, match="temporal"):
        seed(corpus, out)
    assert not out.exists()


def test_source_is_read_only(corpus):
    before = {str(path): path.read_bytes() for path in corpus.rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="read-only"):
        seed(corpus, corpus / "seeded")
    assert before == {str(path): path.read_bytes() for path in corpus.rglob("*") if path.is_file()}


def test_timestamp_dates_and_existing_hijri_year_are_preserved(corpus, tmp_path):
    for path in (corpus / "csv").glob("*.csv"):
        fields, rows = read_csv(path)
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields + ["hijri_year"])
            writer.writeheader()
            for row in rows:
                row["date"] += "T23:30:00-08:00" if row["date"] else ""
                writer.writerow({**row, "hijri_year": "keep"})
    out = tmp_path / "seeded"
    for case in seed(corpus, out):
        transform = case["transformation"]
        if transform["kind"] != "hijri_year":
            continue
        assert transform["added_column"] == "hijri_year_seeded"
        _, source = read_csv(corpus / "csv" / f'{case["source_dataset_id"]}.csv')
        _, rows = read_csv(out / case["csv"])
        for before, after in zip(source, rows, strict=True):
            assert after["date"] == before["date"]
            assert after["hijri_year"] == "keep"
            assert after["hijri_year_seeded"] == (to_hijri_iso(before["date"][:10])[:4] if before["date"] else "")


def test_saved_cases_have_all_twenty_outputs():
    from evals.designer.agent.corpus_tools.seed import OUT

    cases = json.loads((OUT / "seeded.json").read_text(encoding="utf-8"))
    assert len(cases) == 20
    assert {path.name for path in OUT.glob("*.csv")} == {case["csv"] for case in cases}
    for case in cases:
        fields, rows = read_csv(OUT / case["csv"])
        assert rows and case["transformation"]["column"] in fields
