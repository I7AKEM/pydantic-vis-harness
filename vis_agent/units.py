"""Canonical names and display policy for explicitly declared measurement units."""

import unicodedata


PERCENT_UNITS = frozenset({
    "%", "٪", "percent", "percentage", "per cent", "pct",
    "نسبة مئوية", "النسبة المئوية", "بالمئة", "بالمائة", "في المئة", "في المائة",
})


def canonical_unit(unit: str | None) -> str | None:
    """Recognize exact percent aliases, without inferring or converting a scale.

    Percentage points, fractions, and compound or unknown units stay verbatim.
    This function changes a unit's spelling only; it never changes a value.
    """
    if unit is None:
        return None
    normalized = " ".join(unicodedata.normalize("NFKC", unit).casefold().split())
    return "%" if normalized in PERCENT_UNITS else unit

COUNT_UNITS = frozenset({
    "count", "counts", "number", "n", "عدد", "رقم",
})


def display_unit(unit: str | None) -> str | None:
    """A count noun belongs in the measurement label, not after its number."""
    return None if unit is not None and unit.strip().casefold() in COUNT_UNITS else canonical_unit(unit)


COUNT_NOUNS = {
    "person": ({"person", "persons", "people", "شخص", "أشخاص", "اشخاص", "فرد", "أفراد", "افراد", "نسمة", "نسمات"},
               ("person", "people"), ("شخص", "شخصان", "أشخاص", "شخصًا")),
    "user": ({"user", "users", "مستخدم", "مستخدمون", "مستخدمين"},
             ("user", "users"), ("مستخدم", "مستخدمان", "مستخدمين", "مستخدمًا")),
    "order": ({"order", "orders", "طلب", "طلبات"},
              ("order", "orders"), ("طلب", "طلبان", "طلبات", "طلبًا")),
}


def indicator_unit(unit: str | None, value: int | float | None, language: str) -> str | None:
    """Show meaningful supplied units, localizing a bounded set of count nouns.

    This is display grammar only. Values and source units stay in the report;
    unknown and compound units are returned verbatim.
    """
    if unit is None or unit.strip().casefold() in COUNT_UNITS:
        return None
    normalized = unit.strip().casefold()
    for aliases, english, arabic in COUNT_NOUNS.values():
        if normalized not in aliases:
            continue
        amount = abs(value) if value is not None else None
        if language != "ar":
            return english[0] if amount == 1 else english[1]
        if amount == 1:
            return arabic[0]
        if amount == 2:
            return arabic[1]
        if amount is None or amount == 0 or (amount == int(amount) and 3 <= amount <= 10):
            return arabic[2]
        return arabic[3]
    return canonical_unit(unit)
