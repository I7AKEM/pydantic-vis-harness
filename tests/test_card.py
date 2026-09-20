# tests/test_card.py
from vis_agent.analyst.models import ResultColumn
from vis_agent.card import card
from vis_agent.designer.models import Compromise

COLUMNS = [ResultColumn(name="region", meaning="Region", kind="category"),
           ResultColumn(name="total", meaning="Total", kind="measure")]


def test_the_card_holds_everything_the_user_must_see():
    text = card(language="English", png_url="/renders/abc/chart.png", summary="West leads.",
                explanation="A bar compares the regions.", columns=COLUMNS, rows=[["West", 20], ["East", 10]],
                row_count=2, assumptions=["Nulls dropped"], compromises=[Compromise(key="zero", message="The axis starts at 5.")],
                warnings=["w1"], artifact_id="art_1", request_id="rq_1")
    for piece in ("![chart](/renders/abc/chart.png)", "West leads.", "A bar compares the regions.", "| Region | Total |",
                  "| West | 20 |", "2 of 2 rows", "**Assumptions**", "- Nulls dropped", "**Compromises**",
                  "- The axis starts at 5.", "**Warnings**", "- w1", "Artifact art_1 · Request rq_1"):
        assert piece in text, piece
    assert "**Review**" not in text


def test_the_card_speaks_arabic_and_says_why_there_is_no_chart():
    text = card(language="Arabic", no_chart_reason="النتيجة رقم واحد.", columns=COLUMNS, rows=[["غرب", 20]], row_count=1,
                artifact_id="art_1", request_id="rq_1")
    assert "**بلا رسم**: النتيجة رقم واحد." in text and "1 من 1 صفًا" in text and "المخرج art_1 · الطلب rq_1" in text


def test_the_card_shows_twenty_rows_and_the_review():
    rows = [[f"r{i}", i] for i in range(25)]
    review = {"status": "reviewed", "verdict": "revise",
              "review": {"findings": [{"rule": "R-1", "level": "error", "owner": "designer", "message": "Bar 3 is unlabelled."},
                                      {"rule": "S5", "level": "warning", "owner": "designer", "message": "Long labels."}]}}
    text = card(language="English", columns=COLUMNS, rows=rows, row_count=25, review=review, artifact_id="a", request_id="r")
    assert text.count("\n| r") == 20 and "20 of 25 rows" in text
    assert "**Review**: revise" in text and "- Bar 3 is unlabelled." in text and "Long labels." not in text
    assert "**Review**" not in card(language="English", review={"status": "not_reviewed"}, artifact_id="a", request_id="r")
