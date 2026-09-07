"""Render resolved GPT-Vis configurations with the pinned Node package."""

import base64
import html
import json
import re
import shutil
import subprocess
import tempfile
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
    table_html = ""
    if spec.type == "table":
        names = resolved.config["columns"]
        headings = "".join(f"<th scope=\"col\">{html.escape(name)}</th>" for name in names)
        rows = "".join("<tr>" + "".join(
            f"<td>{html.escape(str(row[name])) if row[name] is not None else ''}</td>" for name in names
        ) + "</tr>" for row in resolved.config["data"])
        table_html = f"<table><thead><tr>{headings}</tr></thead><tbody>{rows}</tbody></table>"
    values = {
        "lang": spec.language, "dir": spec.direction or ("rtl" if spec.language == "ar" else "ltr"),
        "title": html.escape(spec.title or "Chart"), "description": html.escape(spec.description or ""),
        "png": base64.b64encode(png.read_bytes()).decode("ascii"),
        "width": str(resolved.width), "height": str(resolved.height),
        "g2": _inline_json(metrics["g2"]), "format": _inline_json(resolved.number.model_dump()),
        "format2": _inline_json(resolved.number2.model_dump() if resolved.number2 else None),
        "format_js": SCRIPT.with_name("format.js").read_text(encoding="utf-8").replace("export ", ""),
        "interactive": str(not metrics["functionPaths"] and spec.type != "table").lower(), "table": table_html,
    }
    page = SCRIPT.with_name("page.html").read_text(encoding="utf-8")
    # Replace original placeholders from the end so inserted user content is never templated.
    for match in reversed(list(re.finditer(r"{{(\w+)}}", page))):
        page = page[:match.start()] + page[match.start():].replace(match[0], values[match[1]], 1)
    return page


def render(spec: Spec, columns: list[ResultColumn], result: QueryResult, out_dir: Path,
           *, trace: bool = False) -> Rendered:
    if reason := available():
        raise RendererUnavailable(reason)
    resolved = resolve(spec, columns, result)
    out_dir.mkdir(parents=True, exist_ok=True)
    png, config, page = (out_dir / name for name in ("chart.png", "config.json", "chart.html"))
    payload = {"config": resolved.config, "overrides": resolved.overrides,
               "format": resolved.number.model_dump(),
               "format2": resolved.number2.model_dump() if resolved.number2 else None,
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
        config.write_text(json.dumps({"gptvis": resolved.config, "overrides": resolved.overrides,
                                     "number": resolved.number.model_dump(), "g2": metrics["g2"],
                                     "number2": payload["format2"],
                                     "functionPaths": metrics["functionPaths"]}, ensure_ascii=False, indent=2), encoding="utf-8")
        page.write_text(_page(spec, resolved, metrics, png), encoding="utf-8")
        compromises = list(resolved.compromises)
        if metrics["functionPaths"]:
            compromises.append(Compromise(key="page", message="the page shows the picture, not an interactive chart, because the package's configuration holds functions"))
        return Rendered(png=png, html=page, config=config, width=metrics["width"], height=metrics["height"],
                        seconds=metrics["renderMs"] / 1000, non_background_share=metrics["nonBackgroundShare"],
                        compromises=compromises, drawn_rows=resolved.drawn_rows, folded_rows=resolved.folded_rows,
                        dropped_rows=resolved.dropped_rows, texts=metrics["texts"] if trace else None)
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
