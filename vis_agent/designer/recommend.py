"""Deterministic bindings and explainable catalogue rankings."""

from vis_agent.analyst.models import QueryResult, ResultColumn
from vis_agent.models import Intent

from .catalogue import CATALOGUE, CatalogueEntry
from .fold import Folded, fold, foldable
from .models import Candidate, Recommendation, Rejection, RuleScore
from .rules import ADDITIVE, Context, HARD_RULES, SOFT_RULES
from .shape import ColumnShape, ResultShape, describe


def default_binding(
    entry: CatalogueEntry, shape: ResultShape, folded: Folded | None = None,
) -> dict[str, ColumnShape] | None:
    binding: dict[str, ColumnShape] = {}
    labels = sorted(shape.labels, key=lambda c: -c.distinct)
    # Bind in dependency order: group excludes category; value2 follows value.
    for role in ("category", "time", "x", "y", "value", "value2", "group"):
        if role not in entry.roles:
            continue
        if role == "category":
            choices = [c for c in labels if folded is None or c.name != folded.series]
            if not choices and entry.name in ("column", "bar", "dual_axes", "grouped_column", "stacked_column"):
                choices = shape.times
        elif role == "time":
            choices = shape.times or [c for c in shape.labels if c.kind == "ordinal"]
        elif role == "group":
            if folded is not None:
                choices = [shape.column(folded.series)]
            else:
                choices = sorted(shape.labels, key=lambda c: c.distinct)
                if "category" in binding:
                    choices = [c for c in choices if not shape.is_alias(c.name, binding["category"].name)]
        else:
            choices = shape.measures
            if folded is not None and role == "value":
                choices = [shape.column(folded.value)]
            if role == "value" and entry.name in ("pie", "donut", "treemap"):
                choices = sorted(choices, key=lambda c: (
                    0 if c.kind == "share" and c.sums_to_whole is True else
                    1 if c.kind == "measure" and c.aggregate in ADDITIVE else
                    2 if c.kind == "share" else 3
                ))
        used = {c.name for c in binding.values()}
        match = next((c for c in choices if c.name not in used and c.kind in entry.roles[role].kinds), None)
        if role == "category" and match is not None:
            match = max((c for c in choices if c.kind in entry.roles[role].kinds and
                         (c.name == match.name or shape.is_alias(c.name, match.name))),
                        key=lambda c: c.longest_label)
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
    names = foldable(columns)
    folded = fold(columns, result, names) if names else None
    folded_shape = describe(folded.columns, folded.result) if folded else None
    context = Context(intent=intent, suggested=suggested)
    candidates, rejected = [], []
    for entry in CATALOGUE.entries:
        used_shape, used_fold = shape, []
        binding = default_binding(entry, shape)
        # A chart that needs a series column gets one folded from the same-unit measures, when nothing else binds it.
        if binding is None and folded is not None and "group" in entry.roles and entry.roles["group"].required:
            binding = default_binding(entry, folded_shape, folded)
            used_shape, used_fold = folded_shape, names
        if binding is None:
            rejected.append(Rejection(name=entry.name, rule="H1",
                                      explanation="Required roles need columns of allowed kinds. Choose a chart that fits the columns."))
            continue
        failure = next((r for rule in HARD_RULES
                        if (r := rule(entry, used_shape, binding, context)) is not None), None)
        if failure is not None:
            rejected.append(Rejection(name=entry.name, rule=failure.rule,
                                      explanation=f"{failure.explanation} {failure.fix}".strip()))
            continue
        breakdown = []
        for rule in SOFT_RULES:
            scored = rule(entry, used_shape, binding, context)
            if scored is not None:
                breakdown.append(RuleScore(rule=scored.rule, score=scored.score,
                                           explanation=f"{scored.explanation} {scored.fix}".strip()))
        candidates.append(Candidate(name=entry.name, score=sum(r.score for r in breakdown),
                                    binding={role: c.name for role, c in binding.items()
                                             if not used_fold or role not in ("group", "value")},
                                    fold=used_fold, breakdown=breakdown))
    candidates.sort(key=lambda c: -c.score)
    return Recommendation(candidates=candidates, rejected=rejected)
