# vis_agent/reviewer/rubric.py
"""The reviewer's own rules, for what code cannot check, and how it treats what the team already conceded."""

REVIEWER_RULES = [
    ("R-1", "error", "The numbers and labels in the picture match the rows: each mark pairs with its label, and the "
                     "axis range matches the values."),
    ("R-2", "warning", "The picture is readable: no truncated or overlapping labels, legible text, a legend that matches "
                       "the series. A label that cannot be read at all is an error."),
    ("R-3", "error", "The chart answers the question asked, for the place, period, and measure it names."),
    ("R-4", "warning", "The title, the axis titles, and the explanation are true to the picture and in the caller's "
                       "language. A title that states what the picture does not show is an error."),
    ("R-5", "error", "Nothing misleads: the baseline, the sort, the emphasis, a colour that implies a meaning it does "
                     "not have."),
]


def rubric_text() -> str:
    lines = ["Rules:"]
    lines += [f"- {rule} ({level}): {text}" for rule, level, text in REVIEWER_RULES]
    lines += [
        "",
        "The compromises and warnings in your input were already conceded by the team: do not report them again; "
        "weigh only whether they mislead, and if one does, say so under R-5.",
        "Owners: designer for the spec (type, bindings, sort, titles, labels, colours); analyst for the table (a "
        "missing series, the wrong grain, a missing filter); renderer for the drawing (truncation, overlap); user for a "
        "decision only the caller can make; none when nothing can change it.",
    ]
    return "\n".join(lines)
