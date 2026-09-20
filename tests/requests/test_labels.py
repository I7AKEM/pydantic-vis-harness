"""A published label mapping stays consistent with upstream metadata and saved raw facts."""

import asyncio

from pydantic_ai.models.function import FunctionModel

from tests.requests.conftest import CHART_SPEC, call, prompt_of
from vis_agent.models import DataBrief, DisplayLabels
from vis_agent.requests.models import Caller
from vis_agent.requests.service import create_request, outcome_for, run_request
from vis_agent.reviewer.agent import build_prompt as review_prompt


def test_supplied_labels_survive_design_publication_and_later_brief_changes(
    deps, dataset_id, agents, fake_models, fake_render,
):
    approved = DisplayLabels(column_labels={"region": "المنطقة", "amount": "المبيعات"},
                             value_labels={"region": {"East": "الشرقية", "West": "الغربية"}})
    brief = DataBrief(producer_agent="data-agent", code_meanings={"region": {"East": "Eastern region"}},
                      display_labels={"ar": approved})
    deps.store.update_brief(dataset_id, brief)

    def design(messages, info):
        prompt = prompt_of(messages)
        assert prompt["code_meanings"]["region"]["East"] == "Eastern region"
        assert prompt["display_labels"] == approved.model_dump()
        # Even a model's conflicting wording cannot replace an approved upstream label.
        spec = CHART_SPEC + 'language ar\nvalueLabels\n  - ["region", "East", "Invented region"]\n'
        return call("deliver_design", spec=spec, explanation="مقارنة المبيعات حسب المنطقة.")

    request = create_request(deps, type="new", dataset_id=dataset_id, question="قارن المبيعات حسب المنطقة",
                             caller=Caller(kind="agent"))
    with agents[2].override(model=FunctionModel(design)):
        outcome = asyncio.run(run_request(deps, request.request_id))
    assert outcome.status == "done"
    assert outcome.artifact.display_labels == approved
    assert outcome.artifact.rows == [["East", 10], ["West", 20]]
    assert "| المنطقة | المبيعات |" in outcome.card
    assert "| الشرقية | 10 |" in outcome.card and "| الغربية | 20 |" in outcome.card
    assert "Invented region" not in outcome.artifact.spec
    assert fake_models[0] == {"profiler": 0, "analyst": 0}
    saved = deps.requests.get_artifact(outcome.artifact.artifact_id)
    review = review_prompt(saved.report, saved.design, brief, (), (), 1)
    assert review.display_labels == approved
    assert review.code_meanings["region"]["East"] == "Eastern region"
    assert review.rows == [["East", 10], ["West", 20]]

    deps.store.update_brief(dataset_id, DataBrief(display_labels={"ar": DisplayLabels(
        value_labels={"region": {"East": "اسم جديد"}},
    )}))
    recalled = asyncio.run(outcome_for(deps, deps.requests.get_request(request.request_id)))
    assert recalled.card == outcome.card  # Existing artifacts snapshot their own display metadata.


def test_numeric_upstream_codes_remain_categories_without_changing_source_values(store):
    from vis_agent.analyst.source import load_csv_report
    from vis_agent.labels import project_display_labels

    brief = DataBrief(code_meanings={"sex": {"1": "Male", "2": "Female"}, "count": {}}, display_labels={
        "ar": DisplayLabels(value_labels={"sex": {"1": "ذكر", "2": "أنثى"}}),
    })
    source = store.save_upload("codes.csv", b"sex,count\n1,10\n2,20\n", brief)
    report = load_csv_report(store, source.dataset_id, "ارسم العدد")
    assert report.analysis.columns[0].kind == "category"
    assert report.analysis.columns[1].kind == "measure"
    assert report.result.rows == [[1, 10], [2, 20]]
    meanings, labels = project_display_labels(brief, report.analysis.columns, "Arabic")
    assert meanings["sex"]["1"] == "Male" and labels.value_labels["sex"]["1"] == "ذكر"

    from vis_agent.analyst.agent import LeadAnswer
    answer = LeadAnswer.from_report(report, brief)
    assert answer.rows == [[1, 10], [2, 20]]
    assert "| ذكر | 10 |" in answer.card and "| أنثى | 20 |" in answer.card
