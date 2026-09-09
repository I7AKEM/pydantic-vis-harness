# tests/analyst/test_agent.py
import asyncio
import json

import pytest
from pydantic_ai import capture_run_messages
from pydantic_ai.messages import ModelResponse, RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from vis_agent.analyst.agent import AnalystDeps, ColumnFacts, MAX_QUERY_CALLS, analyze_dataset, build_prompt, prompt_json, create_analyst, detect_language
from vis_agent.analyst.models import Analysis, AnalysisRevision, Clarification, PreviousAnalysis, ResultColumn
from vis_agent.models import DataBrief
from vis_agent.profiler.agent import create_profiler, profile_dataset

COLUMNS = [
    {"name": "region", "meaning": "المنطقة", "kind": "geography", "source": "region"},
    {"name": "total", "meaning": "مجموع المبالغ", "kind": "measure", "unit": "SAR", "source": "amount", "aggregate": "sum"},
]


def sql_for(dataset):
    return f'SELECT region, sum(amount) AS total FROM "{dataset}" GROUP BY 1 ORDER BY 2 DESC'


def tool_call(name, **args):
    return ModelResponse(parts=[ToolCallPart(tool_name=name, args=args)])


def last_return(messages):
    return [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)][-1]


def run(store, profiler, analyst, dataset, question, **kwargs):
    return asyncio.run(analyze_dataset(store, profiler, analyst, dataset, question, **kwargs))


@pytest.fixture
def agents():
    return create_profiler("test"), create_analyst("test")


def test_language_and_prompt(store, people, agents):
    dataset, profile = people
    assert detect_language("ما مجموع المبالغ؟", None, []) == "Arabic"
    assert detect_language("Total amount?", None, []) == "English"
    assert detect_language("", DataBrief(raw_question="كم؟"), ["a"]) == "Arabic"
    assert detect_language("", None, ["المدينة"]) == "Arabic"
    prompt = build_prompt(store, profile, "Total by region", "English")
    assert prompt.table == f'"{dataset}"' and prompt.row_count == 5
    facts = {c.name: c for c in prompt.columns}
    assert facts["gender"].code_meanings == {"F": "Female", "M": "Male"}
    assert facts["wealth_level"].common_values == ["Middle", "Poor", "Rich"]
    assert facts["amount"].minimum == 5 and facts["amount"].maximum == 40 and facts["amount"].unit == "SAR"
    assert facts["day"].earliest == "2026-01-01"
    assert "rows" not in prompt.model_dump_json()

    cities = "Riyadh Jeddah Dammam Mecca Medina Taif Tabuk Abha Jizan Najran Hail Buraydah Yanbu Jubail Khobar".split()
    source = store.save_upload("cities.csv", ("city\n" + "\n".join(cities) + "\n").encode())
    profiler, _analyst = agents
    profile_output = {"description": "Cities.", "row_meaning": "A city.", "questions": [],
                      "columns": [{"name": "city", "meaning": None, "role": "geography", "unit": None,
                                   "confidence": "high", "evidence": "x"}]}
    with profiler.override(model=TestModel(call_tools=[], custom_output_args=profile_output)):
        wide_profile = asyncio.run(profile_dataset(store, profiler, source.dataset_id))
    wide_prompt = build_prompt(store, wide_profile, "Count Jeddah", "English")
    assert wide_prompt.columns[0].distinct_count == 15
    assert len(wide_prompt.columns[0].common_values) == 5
    assert wide_prompt.columns[0].common_values_are_a_sample is True
    assert facts["wealth_level"].common_values_are_a_sample is False


@pytest.mark.parametrize("starting_requests", [0, 7])
def test_query_then_delivery(store, people, agents, starting_requests):
    dataset, _profile = people
    profiler, analyst = agents

    def drive(messages, info):
        calls = [p for m in messages for p in m.parts if isinstance(p, ToolCallPart)]
        if not calls:
            return tool_call("run_query", sql=sql_for(dataset), columns=COLUMNS)
        returned = last_return(messages).model_response_object()
        assert returned["row_count"] == 2 and returned["rows"][0] == ["West", 65]
        return tool_call("deliver_analysis", summary="الغرب يتصدر بمجموع 65 ريال. الشرق 40 ريال.", assumptions=[])

    usage = RunUsage(requests=starting_requests)
    with analyst.override(model=FunctionModel(drive)):
        report = run(store, profiler, analyst, dataset, "ما مجموع المبالغ حسب المنطقة؟", usage=usage)
    assert report.language == "Arabic" and report.clarification is None
    assert report.analysis.sql == sql_for(dataset)
    assert [c.name for c in report.analysis.columns] == ["region", "total"]
    assert report.result.rows == [["West", 65], ["East", 40]]
    assert report.warnings == [] and usage.requests == starting_requests + 2
    assert report.model is not None and report.seconds >= 0


def test_delivery_needs_a_passing_query_and_true_numbers(store, people, agents):
    dataset, _profile = people
    profiler, analyst = agents
    attempts = []

    def drive(messages, info):
        attempts.append(len(messages))
        retries = [p for m in messages for p in m.parts if isinstance(p, RetryPromptPart)]
        if len(attempts) == 1:
            return tool_call("deliver_analysis", summary="Nothing yet.")
        if len(attempts) == 2:
            assert "run_query" in retries[-1].content
            return tool_call("run_query", sql=sql_for(dataset), columns=COLUMNS)
        if len(attempts) == 3:
            return tool_call("deliver_analysis", summary="West leads with 99 SAR.")
        assert "99" in retries[-1].content
        return tool_call("deliver_analysis", summary="West leads with 65 SAR.")

    with analyst.override(model=FunctionModel(drive)):
        report = run(store, profiler, analyst, dataset, "Total by region")
    assert report.analysis.summary == "West leads with 65 SAR." and len(attempts) == 4
    assert [c.check for c in report.checks if not c.passed] == []


def test_repair_after_a_query_error_and_the_call_cap(store, people, agents):
    dataset, _profile = people
    profiler, analyst = agents
    seen = []

    def drive(messages, info):
        calls = [p for m in messages for p in m.parts if isinstance(p, ToolCallPart)]
        if calls:
            seen.append(last_return(messages).model_response_object())
        if len(calls) < MAX_QUERY_CALLS:
            return tool_call("run_query", sql=f'SELECT nope FROM "{dataset}"', columns=[{"name": "nope", "meaning": "x", "kind": "measure"}])
        assert "run_query" not in [t.name for t in info.function_tools]
        return tool_call("ask_clarification", question="Which column holds the amount?", reason="The query kept failing.")

    with analyst.override(model=FunctionModel(drive)):
        report = run(store, profiler, analyst, dataset, "Total by region")
    assert "nope" in seen[0]["error"]
    assert report.clarification == Clarification(question="Which column holds the amount?", reason="The query kept failing.")
    assert report.analysis is None and report.result is None


def test_two_queries_in_one_response_past_the_budget_get_one_retry(store, people, agents):
    dataset, _profile = people
    profiler, analyst = agents
    good = f'SELECT region, sum(amount) AS total FROM "{dataset}" GROUP BY 1'
    columns = [{"name": "region", "meaning": "Region", "kind": "geography", "source": "region"},
               {"name": "total", "meaning": "Sum of amount", "kind": "measure", "source": "amount", "aggregate": "sum"}]
    calls = []

    def drive(messages, info):
        calls.append(1)
        if len(calls) < MAX_QUERY_CALLS:
            return tool_call("run_query", sql=good, columns=columns)
        if len(calls) == MAX_QUERY_CALLS:
            return ModelResponse(parts=[ToolCallPart(tool_name="run_query", args={"sql": good, "columns": columns}),
                                        ToolCallPart(tool_name="run_query", args={"sql": good, "columns": columns})])
        retry = [p for p in messages[-1].parts if isinstance(p, RetryPromptPart)]
        assert retry and "query calls" in retry[0].model_response()
        assert "run_query" not in [t.name for t in info.function_tools]
        return tool_call("deliver_analysis", summary="West leads.")

    with analyst.override(model=FunctionModel(drive)):
        report = run(store, profiler, analyst, dataset, "Total by region")
    assert report.analysis is not None and report.analysis.summary == "West leads."


def test_failed_checks_come_back_in_the_tool_result_and_are_recorded(store, people, agents):
    dataset, _profile = people
    profiler, analyst = agents
    filtered = f"SELECT region, sum(amount) AS total FROM \"{dataset}\" WHERE region = 'East' GROUP BY 1"

    def drive(messages, info):
        calls = [p for m in messages for p in m.parts if isinstance(p, ToolCallPart)]
        if not calls:
            return tool_call("run_query", sql=filtered, columns=COLUMNS)
        checks = last_return(messages).model_response_object()["checks"]
        assert [c["check"] for c in checks if not c["passed"]] == ["total_explained"]
        return tool_call("deliver_analysis", summary="East totals 40 SAR.", assumptions=["Only the East region was requested."])

    with analyst.override(model=FunctionModel(drive)):
        report = run(store, profiler, analyst, dataset, "East total")
    assert [c.check for c in report.checks if not c.passed] == ["total_explained"]
    assert len(report.warnings) == 1 and report.analysis.assumptions == ["Only the East region was requested."]


def test_model_failure_is_a_report_with_a_warning(store, people, agents):
    dataset, _profile = people
    profiler, analyst = agents

    def drive(messages, info):
        return ModelResponse(parts=[TextPart(content="I cannot use tools.")])

    with analyst.override(model=FunctionModel(drive)):
        report = run(store, profiler, analyst, dataset, "Total by region")
    assert report.analysis is None and report.clarification is None
    assert report.warnings and "could not answer" in report.warnings[0]


def test_omitted_columns_are_refused_through_the_agent(store, agents):
    profiler, analyst = agents
    source = store.save_upload("places.csv", b'region,WKT\nRiyadh,"MULTIPOLYGON (((45 19,46 20,45 19)))"\nJeddah,"POINT (39 21)"\n')
    profile_output = {"description": "Places.", "row_meaning": "A place.", "questions": [],
                      "columns": [{"name": n, "meaning": None, "role": "geography", "unit": None,
                                   "confidence": "high", "evidence": "x"} for n in ("region", "WKT")]}

    def drive(messages, info):
        calls = [p for m in messages for p in m.parts if isinstance(p, ToolCallPart)]
        if not calls:
            return tool_call("run_query", sql=f'SELECT WKT FROM "{source.dataset_id}"',
                             columns=[{"name": "WKT", "meaning": "Geometry", "kind": "geography", "source": "WKT"}])
        returned = last_return(messages).model_response_object()
        assert "cannot be queried" in returned["error"]
        return tool_call("ask_clarification", question="Which region should I count?", reason="Geometry cannot be queried.")

    with profiler.override(model=TestModel(call_tools=[], custom_output_args=profile_output)):
        with analyst.override(model=FunctionModel(drive)):
            report = run(store, profiler, analyst, source.dataset_id, "Show the geometry")
    assert report.clarification is not None and report.result is None
    assert report.analysis is None


def test_unprofiled_dataset_is_profiled_first(store, agents):
    profiler, analyst = agents
    source = store.save_upload("sales.csv", b"region,amount\nEast,1\nWest,2\n")
    profile_output = {"description": "Sales.", "row_meaning": "A sale.", "questions": [],
                      "columns": [{"name": n, "meaning": None, "role": r, "unit": None, "confidence": "high", "evidence": "x"}
                                  for n, r in (("region", "geography"), ("amount", "measure"))]}

    def drive(messages, info):
        calls = [p for m in messages for p in m.parts if isinstance(p, ToolCallPart)]
        if not calls:
            return tool_call("run_query", sql=f'SELECT sum(amount) AS total FROM "{source.dataset_id}"',
                             columns=[{"name": "total", "meaning": "Total", "kind": "measure", "source": "amount", "aggregate": "sum"}])
        return tool_call("deliver_analysis", summary="The total is 3.")

    with profiler.override(model=TestModel(call_tools=[], custom_output_args=profile_output)):
        with analyst.override(model=FunctionModel(drive)):
            report = run(store, profiler, analyst, source.dataset_id, "Total?")
    assert store.get_profile(source.dataset_id).status == "complete"
    assert report.result.rows == [[3]]


def test_measurement_levels_default_to_empty():
    facts = ColumnFacts(name="value", physical_type="VARCHAR", null_percentage=0, distinct_count=1)
    assert facts.measurement_levels == []


def test_hijri_prompt_and_monthly_delivery(store, hijri, agents):
    dataset, profile = hijri
    _profiler, analyst = agents
    prompt = build_prompt(store, profile, "Total amount by Hijri month", "English")
    deps = AnalystDeps(store=store, profile=profile, prompt=prompt)
    sql = ("SELECT substr(translate(day, '٠١٢٣٤٥٦٧٨٩', '0123456789'), 1, 7) AS month, "
           "sum(CAST(replace(translate(amount, '٠١٢٣٤٥٦٧٨٩٫٬', '0123456789.,'), ',', '') AS DOUBLE)) AS total "
           f'FROM "{dataset}" GROUP BY 1 ORDER BY 1')
    columns = [
        {"name": "month", "meaning": "Hijri month", "kind": "time", "unit": None, "source": "day"},
        {"name": "total", "meaning": "Total amount", "kind": "measure", "source": "amount", "aggregate": "sum"},
    ]

    def drive(messages, info):
        calls = [p for m in messages for p in m.parts if isinstance(p, ToolCallPart)]
        if not calls:
            user_prompt = next(p.content for m in messages for p in m.parts if isinstance(p, UserPromptPart))
            facts = {c["name"]: c for c in json.loads(user_prompt)["columns"]}
            assert "Rules for Hijri dates" in (messages[0].instructions or "")
            assert facts["day"]["physical_type"] == "VARCHAR"
            assert facts["day"]["measurement_levels"] == ["hijri"]
            assert facts["named_day"]["measurement_levels"] == ["hijri"]
            assert facts["amount"]["measurement_levels"] == ["arabic_digits"]
            return tool_call("run_query", sql=sql, columns=columns)
        returned = last_return(messages).model_response_object()
        assert returned["rows"] == [["1399-12", 1234.5], ["1400-01", 25.5], ["1447-03", 30.0], ["1447-04", -5.0]]
        assert all(check["passed"] for check in returned["checks"])
        return tool_call("deliver_analysis", summary="Amounts are grouped by Hijri month. The buckets are chronological.")

    with analyst.override(model=FunctionModel(drive)):
        result = asyncio.run(analyst.run(prompt.model_dump_json(), deps=deps))
    assert isinstance(result.output, Analysis)
    assert result.output.sql == sql
    assert result.output.columns[0].kind == "time" and result.output.columns[0].unit is None
    assert deps.query_calls == 1 and deps.passed is not None
    assert all(check.passed for check in deps.passed.result.checks)


def test_localized_rules_stay_out_of_ordinary_runs(store, people, agents):
    dataset, profile = people
    _profiler, analyst = agents
    prompt = build_prompt(store, profile, "Total amount by region", "English")
    deps = AnalystDeps(store=store, profile=profile, prompt=prompt)
    seen = {}

    def drive(messages, info):
        seen["instructions"] = messages[0].instructions or ""
        return tool_call("ask_clarification", question="Which amount?", reason="Checking the instructions.")

    with analyst.override(model=FunctionModel(drive)):
        asyncio.run(analyst.run(prompt.model_dump_json(), deps=deps))
    assert "Rules that hold in every shape" in seen["instructions"]
    assert "Rules for Hijri dates" not in seen["instructions"]


def test_described_names_may_carry_the_alias_quotes(store, people, agents):
    dataset, profile = people
    _profiler, analyst = agents
    prompt = build_prompt(store, profile, "Total amount by region", "English")
    deps = AnalystDeps(store=store, profile=profile, prompt=prompt)
    sql = f'SELECT region, sum(amount) AS "total" FROM "{dataset}" GROUP BY 1 ORDER BY 1'
    columns = [{"name": '"region"', "meaning": "The region", "kind": "geography", "source": "region"},
               {"name": '"total"', "meaning": "Sum of amount", "kind": "measure", "source": "amount", "aggregate": "sum"}]

    def drive(messages, info):
        calls = [p for m in messages for p in m.parts if isinstance(p, ToolCallPart)]
        if not calls:
            return tool_call("run_query", sql=sql, columns=columns)
        returned = last_return(messages).model_response_object()
        assert all(check["passed"] for check in returned["checks"]), returned["checks"]
        return tool_call("deliver_analysis", summary="Amounts are summed by region.")

    with analyst.override(model=FunctionModel(drive)):
        result = asyncio.run(analyst.run(prompt.model_dump_json(), deps=deps))
    assert isinstance(result.output, Analysis)
    assert [column.name for column in result.output.columns] == ["region", "total"]


def test_a_spent_query_budget_with_no_pass_ends_the_run_with_the_check_messages(store, people, agents):
    dataset, _profile = people
    profiler, analyst = agents
    sql = f'SELECT region, sum(amount) AS total FROM "{dataset}" GROUP BY 1'
    wrong = [{"name": "somewhere", "meaning": "Wrong name", "kind": "geography", "source": "region"},
             {"name": "total", "meaning": "Sum of amount", "kind": "measure", "source": "amount", "aggregate": "sum"}]

    def drive(messages, info):
        queries = [p for m in messages for p in m.parts if isinstance(p, ToolCallPart) and p.tool_name == "run_query"]
        if len(queries) < MAX_QUERY_CALLS:
            return tool_call("run_query", sql=sql, columns=wrong)
        return tool_call("deliver_analysis", summary="لن يصل هذا الملخص.")

    with analyst.override(model=FunctionModel(drive)):
        report = run(store, profiler, analyst, dataset, "إجمالي المبلغ حسب المنطقة")
    assert report.clarification is None
    assert report.analysis is None
    assert "Describe exactly the result columns" in report.warnings[0]
    assert report.warnings[0].startswith("The analyst could not answer")


def test_answers_and_previous_work_reach_the_prompt(store, people):
    from vis_agent.analyst.models import PreviousAnalysis, ResultColumn
    from vis_agent.models import QuestionAnswer

    dataset, profile = people
    plain = build_prompt(store, profile, "Total amount by region", "English")
    assert plain.clarifications == [] and plain.previous is None
    assert '"clarifications"' not in prompt_json(plain) and '"previous"' not in prompt_json(plain)
    prompt = build_prompt(
        store, profile, "Total amount by region", "English",
        clarifications=[QuestionAnswer(question="Which amount?", answer="The amount column")],
        previous=PreviousAnalysis(sql="SELECT 1", columns=[ResultColumn(name="one", meaning="One", kind="measure")],
                                  change="Only the East"),
    )
    assert prompt.clarifications[0].answer == "The amount column" and prompt.previous.change == "Only the East"
    assert '"clarifications"' in prompt_json(prompt) and '"previous"' in prompt_json(prompt)


def test_revise_rules_reach_the_model_only_with_answers_or_previous_work(store, people, agents):
    from vis_agent.models import QuestionAnswer

    dataset, profile = people
    _profiler, analyst = agents
    seen = {}

    def drive(messages, info):
        seen["instructions"] = messages[0].instructions or ""
        return tool_call("ask_clarification", question="Which amount?", reason="Checking the instructions.")

    for clarifications, expected in ([], False), ([QuestionAnswer(question="Which?", answer="This")], True):
        prompt = build_prompt(store, profile, "Total amount by region", "English", clarifications=clarifications)
        deps = AnalystDeps(store=store, profile=profile, prompt=prompt)
        with analyst.override(model=FunctionModel(drive)):
            asyncio.run(analyst.run(prompt_json(prompt), deps=deps))
        assert ("Answers and revisions" in seen["instructions"]) is expected


def test_the_change_and_the_answers_count_as_wording(store, people):
    from vis_agent.analyst.agent import _context
    from vis_agent.analyst.models import PreviousAnalysis
    from vis_agent.models import QuestionAnswer

    dataset, profile = people
    prompt = build_prompt(store, profile, "Total amount by region", "English",
                          clarifications=[QuestionAnswer(question="Which?", answer="income above 60000")],
                          previous=PreviousAnalysis(sql="SELECT 1", columns=[], change="Only 2026"))
    context = _context(AnalystDeps(store=store, profile=profile, prompt=prompt))
    assert "60000" in context and "2026" in context and "Total amount by region" in context


def test_designer_feedback_reaches_the_analyst_and_loads_the_repair_rules(store, people, agents):
    _dataset, profile = people
    _profiler, analyst = agents
    feedback = AnalysisRevision(
        problem="The table has no series column",
        requested_change="One row per month and measure",
        preserve="Both measures and the monthly grain",
    )
    prompt = build_prompt(
        store, profile, "Total amount by region", "English",
        previous=PreviousAnalysis(
            sql="SELECT 1",
            columns=[ResultColumn(name="one", meaning="One", kind="measure")],
            change="One row per month and measure",
            feedback=feedback,
        ),
    )
    serialized = prompt_json(prompt)
    assert '"feedback"' in serialized and feedback.problem in serialized
    seen = {}

    def drive(messages, info):
        seen["instructions"] = messages[0].instructions or ""
        return tool_call("ask_clarification", question="Which amount?", reason="Checking the instructions.")

    deps = AnalystDeps(store=store, profile=profile, prompt=prompt)
    with analyst.override(model=FunctionModel(drive)):
        asyncio.run(analyst.run(serialized, deps=deps))
    assert "A revision the chart designer asked for" in seen["instructions"]
    assert "Answers and revisions" not in seen["instructions"]
