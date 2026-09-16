"""The data agent's completed CSV is the source, not a prompt for a new analysis."""

import pytest

from vis_agent.analyst.models import ResultColumn
from vis_agent.analyst.source import load_csv_report
from vis_agent.models import DataBrief
from vis_agent.store import DatasetStore


def upload(tmp_path, text, brief=None):
    store = DatasetStore(tmp_path)
    source = store.save_upload('answer.csv', text.encode(), brief)
    return store, source.dataset_id


def test_source_preserves_rows_labels_dates_nulls_and_precomputed_values(tmp_path):
    store, dataset_id = upload(tmp_path, 'id,hijri,rate,total\n001,1447/02/01,0.25,400\n002,1447/02/02,,800\n')
    result = load_csv_report(store, dataset_id, 'Show the supplied rates')
    assert result.result.rows == [['001', '1447/02/01', 0.25, 400], ['002', '1447/02/02', None, 800]]
    assert result.result.row_count == 2
    assert result.analysis.sql.startswith('SELECT ')
    assert all(column.aggregate == 'none' for column in result.analysis.columns)
    assert result.model is None
    assert result.warnings == []
    assert store.get_profile(dataset_id) is None


def test_existing_all_null_values_do_not_trigger_missing_data_questions(tmp_path):
    store, dataset_id = upload(tmp_path, 'amount,rate\n12,\n')
    result = load_csv_report(store, dataset_id, 'Chart these metrics')
    assert result.clarification is None
    assert result.warnings == []
    assert result.result.rows == [[12, None]]


def test_source_uses_brief_meaning_and_expert_metadata_without_changing_cells(tmp_path):
    brief = DataBrief(raw_question='Show revenue', units={'amount': 'SAR'}, column_descriptions={'amount': 'Revenue'})
    store, dataset_id = upload(tmp_path, 'year,amount\n2024,12\n2025,17\n', brief)
    report = load_csv_report(store, dataset_id, 'Show revenue', columns=[
        ResultColumn(name='year', meaning='Year', kind='time', aggregate='sum'),
    ])
    assert report.analysis.columns[0].kind == 'time'
    assert report.analysis.columns[0].aggregate == 'none'
    assert report.analysis.columns[1].unit == 'SAR'
    assert report.analysis.columns[1].meaning == 'Revenue'
    assert report.result.rows == [[2024, 12], [2025, 17]]


def test_unknown_or_duplicate_annotations_cannot_create_columns(tmp_path):
    store, dataset_id = upload(tmp_path, 'amount\n12\n')
    unknown = ResultColumn(name='invented', meaning='Invented', kind='measure')
    with pytest.raises(ValueError, match='available CSV columns'):
        load_csv_report(store, dataset_id, 'Plot', columns=[unknown])
    known = unknown.model_copy(update={'name': 'amount'})
    with pytest.raises(ValueError, match='distinct names'):
        load_csv_report(store, dataset_id, 'Plot', columns=[known, known])


def test_source_excludes_geometry_and_large_cells_before_context(tmp_path):
    store, dataset_id = upload(tmp_path, 'name,wkt,secret,amount\nCity,POINT (1 2),' + 'x' * 257 + ',42\n')
    report = load_csv_report(store, dataset_id, 'Plot amount')
    assert report.result.columns == ['name', 'amount']
    assert report.result.rows == [['City', 42]]
    assert 'POINT' not in report.model_dump_json()
    assert 'x' * 257 not in report.model_dump_json()


def test_source_does_not_truncate_supported_labels_or_large_result(tmp_path):
    label = 'x' * 200
    store, dataset_id = upload(tmp_path, 'label,amount\n' + '\n'.join(f'{label},{i}' for i in range(1001)) + '\n')
    report = load_csv_report(store, dataset_id, 'Plot amount')
    assert len(report.result.rows) == 1001
    assert report.result.rows[-1] == [label, 1000]


def test_resource_cap_fails_explicitly_instead_of_sampling_or_aggregating(tmp_path, monkeypatch):
    monkeypatch.setattr('vis_agent.analyst.source.SOURCE_ROW_CAP', 1)
    store, dataset_id = upload(tmp_path, 'amount\n12\n17\n')
    with pytest.raises(ValueError, match='No rows were sampled or aggregated'):
        load_csv_report(store, dataset_id, 'Plot amount')


def test_arabic_numeric_measures_are_parsed_without_changing_hijri_or_identifiers(tmp_path):
    store, dataset_id = upload(tmp_path, 'id,hijri,amount,rate\n٠٠١,١٤٤٧/٠٢/٠١,١٢,٢٫٥\n٠٠٢,١٤٤٧/٠٢/٠٢,١٧,٣٫٧٥\n')
    report = load_csv_report(store, dataset_id, 'اعرض المبالغ')
    assert report.result.rows == [['٠٠١', '١٤٤٧/٠٢/٠١', 12, 2.5], ['٠٠٢', '١٤٤٧/٠٢/٠٢', 17, 3.75]]
    assert report.analysis.columns[1].kind == 'time'
    assert report.analysis.columns[2].kind == 'measure'


def test_explicit_analysis_filters_the_same_source_view_without_losing_labels(tmp_path):
    import asyncio
    import json
    from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart, UserPromptPart
    from pydantic_ai.models.function import FunctionModel
    from vis_agent.analyst.agent import analyze_dataset, create_analyst
    from vis_agent.analyst.models import PreviousAnalysis
    from vis_agent.profiler.agent import create_profiler

    label = 'x' * 200
    store, dataset_id = upload(tmp_path, f'id,hijri,label,amount\n001,1447/02/01,{label},١٢\n002,1447/02/02,other,١٧\n')
    report = load_csv_report(store, dataset_id, 'Show the supplied amounts')
    previous = PreviousAnalysis(sql=report.analysis.sql, columns=report.analysis.columns, change='Keep 001')

    def drive(messages, info):
        if not any(isinstance(part, ToolReturnPart) for message in messages for part in message.parts):
            content = next(part.content for message in messages for part in message.parts if isinstance(part, UserPromptPart))
            prompt = json.loads(content)
            assert prompt['table'] in previous.sql
            return ModelResponse(parts=[ToolCallPart('run_query', {
                'sql': f"SELECT * FROM {prompt['table']} WHERE id = '001'",
                'columns': [column.model_dump() for column in report.analysis.columns],
            })])
        return ModelResponse(parts=[ToolCallPart('deliver_analysis', {'summary': 'The requested source row.'})])

    analyst = create_analyst('test')
    with analyst.override(model=FunctionModel(drive)):
        analyzed = asyncio.run(analyze_dataset(store, create_profiler('test'), analyst, dataset_id,
                                               'Keep 001', previous=previous))
    assert analyzed.result.rows == [['001', '1447/02/01', label, 12]]


def test_prepared_sql_guard_cannot_query_raw_hidden_or_other_dataset_tables(tmp_path):
    from vis_agent.analyst.models import QueryError
    from vis_agent.analyst.query import run_sql
    from vis_agent.analyst.source import prepare_csv_source

    store, dataset_id = upload(tmp_path, 'id,amount\n001,12\n')
    prepared = prepare_csv_source(store, dataset_id)
    for table in (dataset_id, dataset_id + '_source', 'datasets'):
        result = run_sql(store, dataset_id, f'SELECT * FROM "{table}"', table_name=prepared.table)
        assert isinstance(result, QueryError)
    result = run_sql(store, dataset_id, f'SELECT * FROM "{prepared.table}"', table_name=prepared.table)
    assert result.rows == [['001', 12]]
