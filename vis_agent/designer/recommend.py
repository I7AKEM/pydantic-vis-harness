"""Deterministic bindings and explainable catalogue rankings."""

from vis_agent.analyst.models import QueryResult, ResultColumn
from vis_agent.models import Intent

from .catalogue import CATALOGUE, CatalogueEntry
from .models import Candidate, Recommendation, Rejection, RuleScore
from .rules import Context, HARD_RULES, SOFT_RULES
from .shape import ColumnShape, ResultShape, describe


def default_binding(entry: CatalogueEntry, shape: ResultShape) -> dict[str, ColumnShape] | None:
    binding: dict[str, ColumnShape] = {}
    labels = sorted(shape.labels, key=lambda c: -c.distinct)
    # Bind in dependency order: group excludes category; value2 follows value.
    for role in ("category", "time", "x", "y", "value", "value2", "group"):
        if role not in entry.roles:
            continue
        if role == "category":
            choices = labels
            if not choices and entry.name in ("column", "bar", "dual_axes"):
                choices = shape.times
        elif role == "time":
            choices = shape.times or [c for c in shape.labels if c.kind == "ordinal"]
        elif role == "group":
            choices = sorted(shape.labels, key=lambda c: c.distinct)
        else:
            choices = shape.measures
            if role == "value" and entry.name in ("pie", "donut", "treemap"):
                choices = sorted(choices, key=lambda c: c.kind != "share")
        used = {c.name for c in binding.values()}
        match = next((c for c in choices if c.name not in used and c.kind in entry.roles[role].kinds), None)
        if match is not None:
            binding[role] = match
        elif entry.roles[role].required:
            return None
    return binding


def recommend_charts(
    columns: list[ResultColumn], result: QueryResult,
    intent: Intent | None = None, suggested: str | None = None,
) -> Recommendation:
    shape = describe(columns, result)
    if shape.rows == 0:
        return Recommendation(candidates=[], rejected=[Rejection(
            name="*", rule="H12", explanation="The result is empty. Ask, do not draw.",
        )])
    context = Context(intent=intent, suggested=suggested)
    candidates, rejected = [], []
    for entry in CATALOGUE.entries:
        binding = default_binding(entry, shape)
        if binding is None:
            rejected.append(Rejection(name=entry.name, rule="H1",
                                      explanation="Required roles need columns of allowed kinds. Choose a chart that fits the columns."))
            continue
        failure = next((r for rule in HARD_RULES
                        if (r := rule(entry, shape, binding, context)) is not None), None)
        if failure is not None:
            rejected.append(Rejection(name=entry.name, rule=failure.rule,
                                      explanation=f"{failure.explanation} {failure.fix}".strip()))
            continue
        breakdown = []
        for rule in SOFT_RULES:
            scored = rule(entry, shape, binding, context)
            if scored is not None:
                breakdown.append(RuleScore(rule=scored.rule, score=scored.score,
                                           explanation=f"{scored.explanation} {scored.fix}".strip()))
        candidates.append(Candidate(name=entry.name, score=sum(r.score for r in breakdown),
                                    binding={role: c.name for role, c in binding.items()}, breakdown=breakdown))
    candidates.sort(key=lambda c: -c.score)
    return Recommendation(candidates=candidates, rejected=rejected)
