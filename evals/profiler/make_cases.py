"""Writes the profiler evaluation set: CSVs, briefs, and expectations. Deterministic."""

import json
from pathlib import Path

CASES = {
    "sales": {
        "csv": "order_id,region,order_date,amount\n"
               "1001,East,2026-01-03,120.5\n1002,West,2026-01-03,80\n1003,East,2026-01-04,200\n"
               "1004,North,2026-01-05,45.25\n1005,South,2026-01-05,310\n1006,West,2026-01-06,99\n"
               "1007,East,2026-01-07,150\n1008,North,2026-01-08,60\n",
        "brief": {"raw_question": "Sales by region", "units": {"amount": "USD"}},
        "units": {"amount": "USD"},
        "roles": {"order_id": "identifier", "region": "category", "order_date": "time", "amount": "measure"},
        "levels": {"order_id": ["interval", "discrete"], "region": ["nominal"], "order_date": ["time"],
                   "amount": ["interval", "continuous"]},
        "failed_checks": [],
    },
    "quarterly": {
        "csv": "quarter,revenue\nQ1,120\nQ2,135\nQ3,150\nQ4,170\nQ1,180\nQ2,190\nQ3,205\nQ4,230\n",
        "roles": {"quarter": "ordinal", "revenue": "measure"},
        "levels": {"quarter": ["nominal", "ordinal"], "revenue": ["interval", "discrete"]},
        "failed_checks": [],
    },
    "survey": {
        "csv": "respondent_id,satisfied,age\n"
               "r1,yes,34\nr2,no,45\nr3,yes,29\nr4,yes,52\nr5,no,38\nr6,yes,41\nr7,no,60\nr8,yes,25\n",
        "roles": {"respondent_id": "identifier", "satisfied": "boolean", "age": "measure"},
        "levels": {"satisfied": ["nominal"], "age": ["interval", "discrete"]},
        "failed_checks": [],
    },
    "citizens": {
        "csv": "citizen_id,gender,wealthy,income\n"
               "c01,F,true,90000\nc02,M,false,42000\nc03,F,false,38000\nc04,M,true,120000\n"
               "c05,F,true,95000\nc06,M,false,51000\nc07,F,false,47000\nc08,M,true,130000\n",
        "brief": {"raw_question": "نسبة الأثرياء حسب الجنس", "code_meanings": {"gender": {"F": "female", "M": "male"}}},
        "roles": {"citizen_id": "identifier", "gender": "category", "wealthy": "boolean", "income": "measure"},
        "levels": {"gender": ["nominal"], "wealthy": ["nominal"], "income": ["interval", "discrete"]},
        "failed_checks": [],
    },
    "stores": {
        "csv": "store,latitude,longitude,monthly_sales\n"
               "Riyadh Mall,24.7136,46.6753,540000\nJeddah Corniche,21.4858,39.1925,410000\n"
               "Dammam Center,26.4207,50.0888,275000\nMedina Gate,24.5247,39.5692,190000\n",
        "roles": {"store": "category", "latitude": "geography", "longitude": "geography", "monthly_sales": "measure"},
        "levels": {"latitude": ["geographic"], "longitude": ["geographic"]},
        "failed_checks": [],
    },
    "districts_wkt": {
        "csv": "district,boundary\n"
               "Al Olaya,\"POLYGON ((46.67 24.69, 46.69 24.69, 46.69 24.71, 46.67 24.69))\"\n"
               "Al Malaz,\"POLYGON ((46.72 24.66, 46.74 24.66, 46.74 24.68, 46.72 24.66))\"\n",
        "roles": {"district": "geography", "boundary": "geography"},
        "levels": {"district": ["nominal", "geographic"], "boundary": ["nominal", "geographic"]},
        "failed_checks": [],
    },
    "conflict_units": {
        "csv": "product,price\nPen,12 USD\nBook,30 USD\nBag,55 USD\n",
        "brief": {"units": {"price": "USD"}},
        "roles": {"product": "category", "price": "text"},
        "levels": {"price": ["nominal"]},
        "failed_checks": ["brief_unit_fits_numeric_column"],
    },
    "conflict_codes": {
        "csv": "ticket,status\n1,A\n2,B\n3,A\n4,B\n",
        "brief": {"code_meanings": {"status": {"A": "open", "B": "closed", "X": "archived"}}},
        "roles": {"ticket": "identifier", "status": "category"},
        "levels": {"status": ["nominal"]},
        "failed_checks": ["brief_codes_present_in_data"],
    },
    "monthly": {
        "csv": "month,active_users\n" + "".join(
            f"2025-{m:02d}-01,{1000 + 37 * m}\n" for m in range(1, 13)),
        "roles": {"month": "time", "active_users": "measure"},
        "levels": {"month": ["time"], "active_users": ["interval", "discrete"]},
        "failed_checks": [],
    },
    "wide": {
        "csv": "product,jan,feb,mar\nPen,10,12,15\nBook,5,7,6\nBag,2,3,4\n",
        "roles": {"product": "category", "jan": "measure", "feb": "measure", "mar": "measure"},
        "levels": {"jan": ["interval", "discrete"]},
        "failed_checks": [],
    },
    "arabic": {
        "csv": "المدينة,المبيعات,التاريخ\nالرياض,1500,2026-02-01\nجدة,1200,2026-02-01\nالدمام,800,2026-02-02\n"
               "الرياض,1650,2026-02-02\nجدة,1100,2026-02-03\nالدمام,900,2026-02-03\n",
        "roles": {"المدينة": "category", "المبيعات": "measure", "التاريخ": "time"},
        "levels": {"المدينة": ["nominal"], "المبيعات": ["interval", "discrete"], "التاريخ": ["time"]},
        "failed_checks": [],
    },
    "ids": {
        "csv": "order_id,customer_code,sku\n" + "".join(
            f"o{i},{code},SKU-{i:04d}\n" for i, code in enumerate(["ABC", "XYZ", "ABC", "QRS", "XYZ", "LMN"] * 2)),
        "roles": {"order_id": "identifier", "customer_code": "category", "sku": "identifier"},
        "levels": {"order_id": ["nominal"], "customer_code": ["nominal"], "sku": ["nominal"]},
        "failed_checks": [],
    },
}


def write_cases(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    expected = {}
    for name, case in CASES.items():
        (directory / f"{name}.csv").write_text(case["csv"], encoding="utf-8")
        if "brief" in case:
            (directory / f"{name}.brief.json").write_text(json.dumps(case["brief"], ensure_ascii=False), encoding="utf-8")
        expected[name] = {"roles": case["roles"], "levels": case["levels"], "failed_checks": case["failed_checks"],
                          "units": case.get("units", {})}
    (directory / "expected.json").write_text(json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8")
    return expected


if __name__ == "__main__":
    written = write_cases(Path(__file__).with_name("cases"))
    print(f"wrote {len(written)} cases")
