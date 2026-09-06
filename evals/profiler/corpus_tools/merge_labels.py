"""Majority vote over the label files in OUT_DIR, then the place-name rule from deterministic hints; ties are listed for adjudication.

    uv run python evals/profiler/corpus_tools/merge_labels.py OUT_DIR PROMPTS_JSON   # prompts from optimize_instructions.build_prompts
"""
import json, sys
from collections import Counter
from pathlib import Path
S = Path(sys.argv[1]); prompts = json.loads(Path(sys.argv[2]).read_text())
labels = {f.stem.removeprefix("labels-"): json.loads(f.read_text()) for f in sorted(S.glob("labels-*.json"))}
columns = json.loads((S / "columns.json").read_text()); models = list(labels)
expected, ties, rule_overrides = {}, [], []
for name in sorted(columns):
    stats = {c["name"]: c for c in json.loads(prompts[name])["statistics"]["columns"]}
    roles = {}
    for col in [c for c in columns[name] if c != "_rows"]:
        votes = {m: (labels[m].get(name) or {}).get(col, {}).get("role") for m in models}
        counts = Counter(v for v in votes.values() if v); top = counts.most_common(2)
        if top and (len(top) == 1 or top[0][1] > top[1][1]): role = top[0][0]
        else: role = None; ties.append((name, col, votes, columns[name][col]))
        geo = stats[col].get("geographic_role")
        if role and role != "geography" and geo in ("place_name", "latitude", "longitude", "wkt") and not stats[col].get("values_omitted", False) or (geo == "wkt" and role and role != "geography"):
            rule_overrides.append((name, col, role, geo)); role = "geography"
        roles[col] = role
    expected[name] = {"roles": roles, "failed_checks": []}
(S / "expected-draft.json").write_text(json.dumps(expected, ensure_ascii=False, indent=1))
total = sum(len(e["roles"]) for e in expected.values())
print(f"models: {models}\ncolumns: {total} | ties: {len(ties)} | place-name overrides: {len(rule_overrides)}")
for name, col, old, geo in rule_overrides: print(f"  override {name} :: {col}: {old} -> geography (hint {geo}; values {columns[name][col]['common'][:2]})")
for name, col, votes, facts in ties: print(f"\nTIE {name} :: {col}\n  votes {votes}\n  facts {json.dumps(facts, ensure_ascii=False)}")
