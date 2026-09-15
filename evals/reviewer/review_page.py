# evals/reviewer/review_page.py
"""One page to confirm each labelled chart by eye: the picture, the question, the two judges' reasons, a verdict.

Usage: uv run python -m evals.reviewer.review_page [evals/reviewer/labelled]; open labelled/review.html, choose
pass or fail per chart, press Copy verdicts JSON, and paste the object into labelled/human.json.
"""

import json
import sys
from datetime import date
from html import escape
from pathlib import Path

from .build_labelled import LABELLED

PAGE = """<!doctype html><meta charset="utf-8"><title>Reviewer labelled set</title>
<style>body{{font:14px system-ui;margin:24px}} .case{{border-top:1px solid #ccc;padding:16px 0}} img{{max-width:900px;display:block}}
pre{{white-space:pre-wrap;background:#f6f6f6;padding:8px}} .judge{{color:#555}}</style>
<h1>{count} charts</h1><p>Reviewer: <input id="by" value="owner"> <button onclick="copy()">Copy verdicts JSON</button></p>
<textarea id="out" rows="4" cols="100"></textarea>
{cases}
<script>
function copy(){{const v={{}};document.querySelectorAll('.case').forEach(c=>{{const s=c.querySelector('select').value;
if(s)v[c.dataset.name]={{verdict:s,note:c.querySelector('textarea').value,by:document.getElementById('by').value,date:'{today}'}};}});
const t=JSON.stringify(v,null,1);document.getElementById('out').value=t;navigator.clipboard&&navigator.clipboard.writeText(t);}}
</script>"""

CASE = """<div class="case" data-name="{name}"><h3>{name}</h3><p dir="auto">{question}</p><img src="{png}">
<pre dir="auto">{spec}</pre><p class="judge">A ({a_verdict}): {a_reason}</p><p class="judge">B ({b_verdict}): {b_reason}</p>
<p><select><option value="">—</option><option value="pass">pass</option><option value="fail">fail</option></select>
<textarea rows="2" cols="80" placeholder="what is wrong, or right"></textarea></p></div>"""


def write_review_page(out: Path = LABELLED) -> Path:
    cases = json.loads((out / "cases.json").read_text(encoding="utf-8"))
    blocks = []
    for case in cases:
        judges = case.get("judges", {})
        blocks.append(CASE.format(
            name=escape(case["name"]), question=escape(case["question"]), png=escape(case["png"]),
            spec=escape(case["design"]["spec"]),
            a_verdict=escape(str(judges.get("a", {}).get("verdict"))), a_reason=escape(str(judges.get("a", {}).get("reason"))[:600]),
            b_verdict=escape(str(judges.get("b", {}).get("verdict"))), b_reason=escape(str(judges.get("b", {}).get("reason"))[:600]),
        ))
    page = out / "review.html"
    page.write_text(PAGE.format(count=len(cases), cases="\n".join(blocks), today=date.today().isoformat()), encoding="utf-8")
    return page


if __name__ == "__main__":
    print(write_review_page(Path(sys.argv[1]) if len(sys.argv) > 1 else LABELLED))
