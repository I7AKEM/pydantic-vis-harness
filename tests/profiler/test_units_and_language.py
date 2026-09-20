# tests/profiler/test_units_and_language.py
import asyncio

from pydantic_ai.models.test import TestModel

from vis_agent.language import language_of
from vis_agent.profiler.agent import ProfilerInput, create_profiler
from vis_agent.profiler.models import ColumnSemantics
from vis_agent.profiler.review import failed_checks, run_checks
from tests.conftest import semantic_profile


def column(role, unit):
    return ColumnSemantics(name="c", meaning=None, role=role, unit=unit, confidence="low", evidence="e")


def test_placeholder_units_become_null():
    for word in ("null", "None", " n/a ", "-", "count", "unitless", "عدد", ""):
        assert column("category", word).unit is None, word
    assert column("measure", "SAR").unit == "SAR"
    assert column("measure", None).unit is None


def test_language_of_reads_the_script():
    assert language_of("ما عدد السكان؟") == "Arabic"
    assert language_of("", None, "region gender") == "English"
    assert language_of(None) == "English"


def test_the_agent_output_carries_no_placeholder_unit_and_the_prompt_names_the_language(people):
    _dataset_id, profile = people
    columns = [{"name": c.name, "meaning": "m", "role": "measure" if c.name == "amount" else "category",
                "unit": "null", "confidence": "low", "evidence": "e"} for c in profile.deterministic.columns]
    output = {"description": "People.", "row_meaning": None, "questions": [], "columns": columns}
    profiler = create_profiler("test")
    prompt = ProfilerInput(statistics=profile.deterministic, language="English")
    assert '"language":"English"' in prompt.prompt_json()
    with profiler.override(model=TestModel(call_tools=[], custom_output_args=output)):
        result = asyncio.run(profiler.run(prompt.prompt_json(), deps=prompt))
    assert all(c.unit is None for c in result.output.columns)


def test_a_meaning_in_the_wrong_language_is_a_warning(people):
    _dataset_id, profile = people
    semantic = semantic_profile([c.name for c in profile.deterministic.columns])
    semantic.columns[0].meaning = "المنطقة الإدارية"
    failed = [c for c in failed_checks(run_checks(profile.deterministic, semantic, None, language="English"))
              if c.check == "language_matches"]
    assert len(failed) == 1 and failed[0].severity == "warning" and "region" in failed[0].message
    assert not [c for c in run_checks(profile.deterministic, semantic, None) if c.check == "language_matches"]
