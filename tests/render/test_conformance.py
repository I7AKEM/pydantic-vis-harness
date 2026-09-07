"""The shared base vocabulary agrees with the pinned upstream parser."""

import json
import subprocess

import pytest

from vis_agent.designer.syntax import KEYS, parse
from vis_agent.render.gptvis import SCRIPT, available

pytestmark = pytest.mark.skipif(available() is not None, reason=available() or "")


@pytest.mark.parametrize("text", [
    "vis column\ntitle Cities\naxisXTitle City\naxisYTitle Count",
    "vis line\ntheme dark",
    "vis donut\ninnerRadius 0.6",
    "vis column\nstyle\n  backgroundColor ivory\n  palette\n    - red\n    - blue",
    "vis bar\nwidth 800\nheight 450",
])
def test_base_vocabulary_conforms(text):
    spec = parse(text)
    expected = {"type": spec.type}
    for key, (field, _) in KEYS.items():
        if field in spec.model_fields_set and key != "style" and key != "palette":
            expected[key] = getattr(spec, field)
    if spec.background_color is not None:
        expected["style"] = {"backgroundColor": spec.background_color, "palette": spec.palette}
    process = subprocess.run(["node", str(SCRIPT.with_name("conformance.mjs"))], input=text,
                             text=True, capture_output=True, timeout=20, check=True)
    assert json.loads(process.stdout) == expected
