# evals/reviewer/build_labelled.py
"""Build the reviewer's labelled set from the evaluation team's run: the designer cases both judges agreed on.

Usage: uv run python -m evals.reviewer.build_labelled ~/Downloads/20260913-183937 [evals/reviewer/labelled]
The pictures are copied beside the cases and kept out of git; the human verdicts go to human.json.
"""

import json
import shutil
import sys
from pathlib import Path

LABELLED = Path(__file__).with_name("labelled")


def build_labelled(run: Path, out: Path = LABELLED) -> list[dict]:
    (out / "png").mkdir(parents=True, exist_ok=True)
    cases = []
    for path in sorted((run / "cases").glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        designer = case["stages"].get("designer") or {}
        analyst = case["stages"].get("analyst") or {}
        consensus = designer.get("consensus") or {}
        picture = case.get("harness", {}).get("png_path")
        if designer.get("status") != "judged" or not consensus.get("agree") or not picture:
            continue
        if not (run / picture).is_file() or analyst.get("status") != "judged":
            continue
        name = case["case"]["case_id"]
        shutil.copyfile(run / picture, out / "png" / f"{name}.png")
        cases.append({
            "name": name, "question": case["case"]["question"], "language": case["case"].get("language"),
            "analyst": analyst["output"], "design": designer["output"], "png": f"png/{name}.png",
            "judges": {judge: {"verdict": designer[judge].get("verdict"), "reason": designer[judge].get("reasoning_en")}
                       for judge in ("a", "b") if judge in designer},
            "consensus": consensus.get("consensus"),
        })
    (out / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=1), encoding="utf-8")
    return cases


if __name__ == "__main__":
    run_dir = Path(sys.argv[1]).expanduser()
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else LABELLED
    built = build_labelled(run_dir, out_dir)
    print(f"{len(built)} cases written to {out_dir / 'cases.json'}")
