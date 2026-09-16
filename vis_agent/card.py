"""The card: what the user sees of a result, assembled by code so nothing is dropped and nothing is invented."""

from collections.abc import Sequence

from vis_agent.analyst.models import ResultColumn
from vis_agent.designer.models import Compromise
from vis_agent.models import DisplayLabels
from vis_agent.labels import display_value

CARD_ROWS = 20
LABELS = {
    "English": {"rows": "{shown} of {total} rows", "assumptions": "Assumptions", "compromises": "Compromises",
                "warnings": "Warnings", "review": "Review", "findings": "Open findings", "no_chart": "No chart",
                "ids": "Artifact {artifact} · Request {request}"},
    "Arabic": {"rows": "{shown} من {total} صفًا", "assumptions": "الافتراضات", "compromises": "التنازلات",
               "warnings": "تنبيهات", "review": "المراجعة", "findings": "ملاحظات مفتوحة", "no_chart": "بلا رسم",
               "ids": "المخرج {artifact} · الطلب {request}"},
}


def _cell(value) -> str:
    return "" if value is None else str(value).replace("|", "\\|").replace("\n", " ")


def _table(columns: Sequence[ResultColumn], rows: Sequence[Sequence], total: int, labels: dict,
           display: DisplayLabels) -> str:
    headers = [display.column_labels.get(column.name, column.meaning.strip() or column.name) for column in columns]
    lines = ["| " + " | ".join(_cell(h) for h in headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(_cell(display_value(display, c.name, v)) for c, v in zip(columns, row)) + " |"
              for row in list(rows)[:CARD_ROWS]]
    return "\n".join(lines) + "\n\n" + labels["rows"].format(shown=min(len(rows), CARD_ROWS), total=total)


def _section(title: str, items: Sequence[str]) -> str:
    return f"**{title}**\n" + "\n".join(f"- {item}" for item in items) if items else ""


def _review(review: dict | None, labels: dict) -> str:
    """The reviewer's verdict and the findings still open; nothing until a reviewer has run."""
    if not review or review.get("status") != "reviewed":
        return ""
    findings = review.get("review", {}).get("findings", [])
    open_findings = [f["message"] for f in findings if f.get("level") == "error"]
    return "\n".join(part for part in (f"**{labels['review']}**: {review.get('verdict', '')}",
                                       _section(labels["findings"], open_findings)) if part)


def card(*, language: str, png_url: str | None = None, no_chart_reason: str | None = None, summary: str | None = None,
         explanation: str | None = None, columns: Sequence[ResultColumn] = (), rows: Sequence[Sequence] = (),
         row_count: int = 0, assumptions: Sequence[str] = (), compromises: Sequence[Compromise] = (),
         warnings: Sequence[str] = (), review: dict | None = None, artifact_id: str | None = None,
         request_id: str | None = None, display_labels: DisplayLabels | None = None) -> str:
    """Markdown in the caller's language: picture, summary, explanation, table with its count, assumptions,
    compromises, warnings, review, and the IDs. Every part the lead's instructions once asked the model to assemble."""
    labels = LABELS.get(language, LABELS["English"])
    parts = [
        f"![chart]({png_url})" if png_url else f"**{labels['no_chart']}**: {no_chart_reason}" if no_chart_reason else "",
        summary or "",
        explanation or "",
        _table(columns, rows, row_count, labels, display_labels or DisplayLabels()) if columns else "",
        _section(labels["assumptions"], list(assumptions)),
        _section(labels["compromises"], [c.message for c in compromises]),
        _section(labels["warnings"], list(warnings)),
        _review(review, labels),
        labels["ids"].format(artifact=artifact_id, request=request_id) if artifact_id and request_id else "",
    ]
    return "\n\n".join(part for part in parts if part)
