"""Local-only replay of the retained donut, keeping its original explicit on switches.

Run from the repository root with:
    PYTHONPATH=. .venv/bin/python evals/lead/labels-on-probe/replay_enabled_fix.py
The output is deliberately write-once; the original experiment is never rewritten.
"""

import hashlib
import json
from pathlib import Path

from vis_agent.analyst.models import AnalysisReport
from vis_agent.designer.syntax import parse
from vis_agent.render import gptvis


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def main():
    here = Path(__file__).resolve().parent
    source = here.parent / "results-parallel20-glm-production-v3-assets" / "corpus-vizcsv-6eff7ae46ebb4edf"
    baseline = source / "renders" / "cc842f40687c"
    output = here / "enabled-fix-v1"
    if output.exists():
        raise FileExistsError(f"Preserve existing evidence: {output}")
    originals = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in [source / "case.json", *baseline.iterdir()] if path.is_file()}
    saved = json.loads((source / "case.json").read_text())
    specs = {item["spec"] for item in objects(saved) if isinstance(item.get("spec"), str)}
    assert len(specs) == 1
    spec = parse(specs.pop())
    assert spec.labels == spec.legend == "on"
    report = AnalysisReport.model_validate(saved["artifacts"][0]["report"])
    rendered = gptvis.render(spec, report.analysis.columns, report.result, output, trace=True)
    original = json.loads((baseline / "config.json").read_text())
    fixed = json.loads(rendered.config.read_text())
    for key in ("gptvis", "overrides", "number", "number2", "tableFormats", "display"):
        assert fixed[key] == original[key], key
    assert {key: value for key, value in fixed["g2"].items() if key not in {"labels", "legend"}} == {
        key: value for key, value in original["g2"].items() if key not in {"labels", "legend"}
    }
    assert fixed["g2"]["labels"][0]["position"] == "outside"
    assert {"type": "overlapHide"} in fixed["g2"]["labels"][0]["transform"]
    assert fixed["g2"]["legend"]["color"]["position"] == "bottom"
    assert fixed["g2"]["legend"]["color"]["layout"] == {"justifyContent": "center"}
    assert rendered.drawn_rows == 2 and rendered.dropped_rows == rendered.folded_rows == 0
    assert any("373,877" in text and "مواطن" in text for text in rendered.texts)
    assert any("375,161" in text and "وافد" in text for text in rendered.texts)
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in originals.items())
    print(json.dumps({"png": str(rendered.png), "width": rendered.width, "height": rendered.height,
                      "drawn_rows": rendered.drawn_rows, "render_seconds": rendered.seconds,
                      "png_sha256": hashlib.sha256(rendered.png.read_bytes()).hexdigest(),
                      "original_evidence_unchanged": True, "same_spec_and_data": True,
                      "changed_g2_keys": ["labels", "legend"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
