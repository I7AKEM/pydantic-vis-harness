"""Render resolved GPT-Vis configurations with the pinned Node package."""

import base64
import html
import json
import re
import shutil
import subprocess
import tempfile
import unicodedata
from collections.abc import Sequence
from pathlib import Path

from vis_agent.analyst.models import QueryResult, ResultColumn
from vis_agent.designer.models import ChartType, Compromise, Spec
from vis_agent.designer.resolve import resolve
from vis_agent.designer.syntax import KEYS, STYLE_KEYS

from .base import RENDERERS, Capability, Rendered, RendererUnavailable, RenderFailed

SCRIPT = Path(__file__).with_suffix("") / "render.mjs"
NODE_TIMEOUT_SECONDS = 20
INSTALL = "npm ci --prefix vis_agent/render/gptvis"

GPTVIS_HONOURED = set(KEYS) | set(STYLE_KEYS) | {"bind"}
GPTVIS_DEGRADED = {
    "direction": "the legend stays where the package puts it; the title and the category order follow the direction",
}


def capability(chart_type: ChartType) -> Capability:
    if chart_type == "indicator":
        honoured = {"cards", "columnLabels", "valueLabels", "title", "subtitle", "description", "language", "theme", "width", "height",
                    "direction", "digits", "backgroundColor", "palette", "style"}
        return Capability(honoured=honoured, degraded={}, rejected={
            key: "indicators use card bindings and have no chart axes or row transforms"
            for key in GPTVIS_HONOURED - honoured
        })
    degraded = GPTVIS_DEGRADED
    if chart_type == "table":
        degraded = dict.fromkeys(
            ("subtitle", "labels", "legend", "axisXTitle", "axisYTitle", "direction", "format"),
            "tables are drawn as the package draws them",
        )
    return Capability(honoured=GPTVIS_HONOURED, degraded=degraded, rejected={})


RENDERERS["gptvis"] = capability


def available() -> str | None:
    if shutil.which("node") is None:
        return f"Node is not installed; install Node 22 or later, then run {INSTALL}"
    if not (SCRIPT.parent / "node_modules" / "@antv" / "gpt-vis-ssr").is_dir():
        return f"GPT-Vis SSR is not installed; run {INSTALL}"
    return None


def _inline_json(value) -> str:
    # HTML closes script elements case-insensitively, even inside JSON strings.
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _page(spec: Spec, resolved, metrics: dict, png: Path) -> str:
    if spec.type == "indicator":
        return _indicator_page(spec, resolved, png)
    table_html = ""
    if spec.type == "table":
        names = resolved.config["columns"]
        def cell_html(name, value):
            text = "" if value is None else str(value)
            escaped = html.escape(text)
            if (name in resolved.display.get("timeFields", []) and re.search("[٠-٩]", text)
                    and re.fullmatch(r"[0-9٠-٩TZ :./+\-]+", text)):
                return f'<bdi dir="ltr" style="unicode-bidi: bidi-override">{escaped}</bdi>'
            return escaped
        headings = "".join(f"<th scope=\"col\">{html.escape(resolved.display['columns'].get(name, name))}</th>" for name in names)
        rows = "".join("<tr>" + "".join(
            f"<td>{cell_html(name, row[name])}</td>" for name in names
        ) + "</tr>" for row in metrics["tableDisplay"])
        table_html = f"<table><thead><tr>{headings}</tr></thead><tbody>{rows}</tbody></table>"
    values = {
        "lang": spec.language, "dir": spec.direction or ("rtl" if spec.language == "ar" else "ltr"),
        "title": html.escape(spec.title or "Chart"), "description": html.escape(spec.description or ""),
        "png": base64.b64encode(png.read_bytes()).decode("ascii"),
        "width": str(resolved.width), "height": str(resolved.height),
        "g2": _inline_json(metrics["g2"]), "format": _inline_json(resolved.number.model_dump()),
        "format2": _inline_json(resolved.number2.model_dump() if resolved.number2 else None),
        "format_js": SCRIPT.with_name("format.js").read_text(encoding="utf-8").replace("export ", ""),
        "display_js": SCRIPT.with_name("display.js").read_text(encoding="utf-8").replace("export ", ""),
        "display": _inline_json(resolved.display),
        "interactive": str(not metrics["functionPaths"] and spec.type != "table").lower(), "table": table_html,
    }
    page = SCRIPT.with_name("page.html").read_text(encoding="utf-8")
    # Replace original placeholders from the end so inserted user content is never templated.
    for match in reversed(list(re.finditer(r"{{(\w+)}}", page))):
        page = page[:match.start()] + page[match.start():].replace(match[0], values[match[1]], 1)
    return page


def _indicator_page(spec: Spec, resolved, png: Path) -> str:
    """A portable static image with the same escaped, accessible card text."""
    def number_html(text):
        match = re.match(r"([+\-]?[\d٬٫,.]+(?:[eE][+\-]?\d+)?[KMB]?%?)(.*)", text, re.DOTALL)
        if match is None:
            return html.escape(text)
        # Keep signs/exponents in order; the unit keeps normal Arabic shaping.
        numeric, suffix = match.groups()
        suffix_html = f'<bdi dir="auto">{html.escape(suffix)}</bdi>' if suffix else ""
        return f'<bdi dir="ltr" style="unicode-bidi: bidi-override">{html.escape(numeric)}</bdi>{suffix_html}'

    def metric(item, primary=False):
        unit = f'<bdi dir="auto" class="metric-unit">{html.escape(item["unitLabel"])}</bdi>' if item["unitLabel"] else ""

        def amount(text):
            value = f'{number_html(text)} {unit}'
            return f'<bdi dir="ltr" class="metric-percent">{value}</bdi>' if item["unitLabel"] == "%" else value

        exact = f'<small>{amount(item["exactNumber"])}</small>' if item["exactNumber"] else ""
        kind = ' class="primary"' if primary else ""
        return (f'<dt>{html.escape(item["label"])}</dt>'
                f'<dd{kind} data-state="{item["state"]}">{amount(item["number"])}{exact}</dd>')

    def context(item):
        numeric_token = re.fullmatch(r"[\dTZ :./+\-]+", item["text"]) is not None
        direction, bidi = ("ltr", "bidi-override") if numeric_token else ("auto", "isolate")
        return (f'<dt>{html.escape(item["label"])}</dt><dd><bdi dir="{direction}" '
                f'style="unicode-bidi: {bidi}">{html.escape(item["text"])}</bdi></dd>')

    sections = []
    def normalized_label(text):
        return " ".join(unicodedata.normalize("NFKC", text or "").lower().split())

    for card in resolved.config["cards"]:
        context_html = "".join(context(item) for item in card["context"])
        support = "".join(metric(item) for item in card["support"])
        redundant_description = normalized_label(spec.description) in {
            normalized_label(card["value"]["label"]), normalized_label(spec.title),
        }
        footnote = (f'<p class="footnote">{html.escape(spec.description)}</p>'
                    if len(resolved.config["cards"]) == 1 and spec.description and not redundant_description else "")
        sections.append(f'<section><dl>{metric(card["value"], True)}{context_html}{support}</dl>{footnote}</section>')
    title, description = html.escape(spec.title or "Indicator"), html.escape(spec.description or "")
    subtitle = f'<p>{html.escape(spec.subtitle)}</p>' if spec.subtitle else ""
    duplicate_title = len(resolved.config["cards"]) == 1 and normalized_label(resolved.config["cards"][0]["value"]["label"]) == normalized_label(spec.title)
    heading = "" if duplicate_title else f"<h1>{title}</h1>"
    overview = f"<p>{description}</p>" if len(resolved.config["cards"]) > 1 else ""
    image = base64.b64encode(png.read_bytes()).decode("ascii")
    direction = spec.direction or ("rtl" if spec.language == "ar" else "ltr")
    return f'''<!doctype html>
<html lang="{spec.language}" dir="{direction}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>
body {{ font-family: sans-serif; margin: 2rem; color: #182435; background: #fff; }}
img {{ max-width: 100%; height: auto; }}
.metrics {{ display: flex; flex-wrap: wrap; gap: 1.5rem; }}
section {{ border: 1px solid #d5deeb; padding: 1rem; min-width: 12rem; }}
dt {{ font-weight: 600; margin-top: .75rem; }} dd {{ margin: .25rem 0 1rem; overflow-wrap: anywhere; }}
.primary {{ font-size: 2rem; }} .metric-unit {{ font-size: .65em; margin-inline-start: .25em; }}
.footnote {{ font-size: .85rem; color: #506176; }}
small {{ display: block; margin-top: .25rem; }}
</style></head><body>{heading}{subtitle}{overview}
<img src="data:image/png;base64,{image}" width="{resolved.width}" height="{resolved.height}" alt="{description}">
<div class="metrics">{''.join(sections)}</div></body></html>'''


def render(spec: Spec, columns: list[ResultColumn], result: QueryResult, out_dir: Path,
           *, trace: bool = False, compromises: Sequence[Compromise] = ()) -> Rendered:
    if reason := available():
        raise RendererUnavailable(reason)
    resolved = resolve(spec, columns, result)
    out_dir.mkdir(parents=True, exist_ok=True)
    png, config, page = (out_dir / name for name in ("chart.png", "config.json", "chart.html"))
    payload = {"config": resolved.config, "overrides": resolved.overrides,
               "format": resolved.number.model_dump(),
               "format2": resolved.number2.model_dump() if resolved.number2 else None,
               "tableFormats": resolved.table_formats,
               "display": resolved.display,
               "output": str(png.resolve()), "trace": trace}
    try:
        process = subprocess.run(["node", str(SCRIPT), str(png.resolve())], input=json.dumps(payload), text=True,
                                 capture_output=True, timeout=NODE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        raise RenderFailed(f"render timed out after {NODE_TIMEOUT_SECONDS:g} s") from error
    except OSError as error:
        raise RendererUnavailable(f"{error}; install Node 22 or later and run {INSTALL}") from error
    if process.returncode:
        try:
            reason = json.loads(process.stderr)["error"]
        except (ValueError, KeyError, TypeError):
            reason = process.stderr.strip() or f"node exited with status {process.returncode}"
        raise RenderFailed(reason)
    try:
        metrics = json.loads(process.stdout)
        if spec.type == "indicator":
            resolved.width, resolved.height = metrics["logicalWidth"], metrics["logicalHeight"]
            resolved.config["height"] = resolved.height
        if spec.type == "table":
            resolved.config = metrics["config"]
        config.write_text(json.dumps({"gptvis": resolved.config, "overrides": resolved.overrides,
                                     "number": resolved.number.model_dump(), "g2": metrics["g2"],
                                     "number2": payload["format2"],
                                     "tableFormats": resolved.table_formats,
                                     "display": resolved.display,
                                     "functionPaths": metrics["functionPaths"],
                                     **({"texts": metrics["texts"], "textBounds": metrics["textBounds"],
                                         "cardBounds": metrics["cardBounds"]} if spec.type == "indicator" else {})},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
        page.write_text(_page(spec, resolved, metrics, png), encoding="utf-8")
        merged_compromises = list(compromises) + resolved.compromises
        if metrics["functionPaths"]:
            merged_compromises.append(Compromise(key="page", message="the page shows the picture, not an interactive chart, because the package's configuration holds functions"))
        return Rendered(png=png, html=page, config=config, width=metrics["width"], height=metrics["height"],
                        seconds=metrics["renderMs"] / 1000, non_background_share=metrics["nonBackgroundShare"],
                        compromises=list({(c.key, c.message): c for c in merged_compromises}.values()),
                        drawn_rows=resolved.drawn_rows, folded_rows=resolved.folded_rows,
                        dropped_rows=resolved.dropped_rows,
                        texts=metrics["texts"] if trace or spec.type == "indicator" else None,
                        text_bounds=metrics.get("textBounds"))
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise RenderFailed(f"invalid renderer output: {error}") from error


def smoke_test() -> str | None:
    columns = [ResultColumn(name="city", meaning="City", kind="category", aggregate="none"),
               ResultColumn(name="count", meaning="Violations", kind="measure", aggregate="count")]
    rows = [["الرياض", 1240], ["جدة", 980], ["مكة المكرمة", 610], ["المدينة المنورة", 455], ["الدمام", 390]]
    result = QueryResult(sql="", columns=["city", "count"], types=["VARCHAR", "BIGINT"],
                         rows=rows, row_count=len(rows), seconds=0)
    spec = Spec(type="column", language="ar", title="عدد المخالفات حسب المدينة 2025",
                axis_x_title="المدينة", axis_y_title="عدد المخالفات", bind={"category": "city", "value": "count"})
    try:
        with tempfile.TemporaryDirectory(prefix="gptvis-smoke-") as directory:
            rendered = render(spec, columns, result, Path(directory), trace=True)
            if rendered.non_background_share < 0.02 or "الرياض" not in (rendered.texts or []):
                return "fonts: Arabic text did not render"
    except (RendererUnavailable, RenderFailed, OSError) as error:
        return f"renderer unavailable: {error}"
    return None
