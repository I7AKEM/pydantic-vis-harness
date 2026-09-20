# vis_agent/reviewer/rubric.py
"""The reviewer's own rules, for what code cannot check, and how it treats what the team already conceded."""

REVIEWER_RULES = [
    ("R-1", "error", "Every visible number, category label, and mark is paired with the same row and binding."),
    ("R-2", "warning", "Visible text and marks are readable and not clipped or overlapping. Missing or unreadable "
                       "meaning-bearing content is an error."),
    ("R-3", "error", "Visible marks and bound series required by the supplied spec are not blank or missing. "
                     "Do not demand a different chart, unbound column, or new analysis."),
    ("R-4", "warning", "Visible titles, legend text, and localized labels match the spec and caller language; RTL "
                       "placement is not itself a defect."),
    ("R-5", "error", "The visible axis, sort, legend, or colour encoding does not misrepresent the supplied rows."),
]


def rubric_text() -> str:
    lines = ["Rules:"]
    lines += [f"- {rule} ({level}): {text}" for rule, level, text in REVIEWER_RULES]
    lines += [
        "",
        "Compromises and warnings describe known limitations, not proof of correctness or an instruction to fail. "
        "Do not report them again without an independently visible meaning-changing defect.",
        "Owners: designer when a supported spec/configuration change can fix the picture; renderer only for a drawing "
        "failure the spec cannot control; none when nothing in this visual pipeline can change it. Findings owned by "
        "analyst or user are outside your scope and must not be emitted.",
    ]
    return "\n".join(lines)
