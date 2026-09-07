import pytest

from vis_agent.profiler.measurements import compute_statistics


def profile_of(store, name, content):
    source = store.save_upload(name, content)
    store.import_csv(source.dataset_id)
    profile = compute_statistics(store, source)
    return {column.name: column for column in profile.columns}


def test_numeric_columns_get_interval_plus_discrete_or_continuous(store):
    columns = profile_of(store, "n.csv", b"count,ratio,whole_float\n1,0.5,2.0\n2,0.25,3.0\n3,0.75,4.0\n")
    assert columns["count"].measurement_levels == ["interval", "discrete"]
    assert columns["count"].integer_valued is True
    assert columns["ratio"].measurement_levels == ["interval", "continuous"]
    assert columns["ratio"].integer_valued is False
    assert columns["whole_float"].measurement_levels == ["interval", "discrete"]


def test_dates_are_time(store):
    columns = profile_of(store, "d.csv", b"day,value\n2026-01-01,1\n2026-01-02,2\n")
    assert columns["day"].measurement_levels == ["time"]
    assert columns["day"].earliest == "2026-01-01"


def test_ordinal_pattern_from_prefix_and_number(store):
    content = b"quarter,week,label\nQ1,Week 1,alpha\nQ2,Week 2,beta\nQ3,Week 10,gamma\nQ4,Week 11,delta\nQ1,Week 1,alpha\nQ2,Week 2,beta\n"
    columns = profile_of(store, "o.csv", content)
    assert columns["quarter"].measurement_levels == ["nominal", "ordinal"]
    assert columns["quarter"].ordinal_pattern == "Q#"
    assert columns["week"].ordinal_pattern == "Week #"
    assert columns["label"].ordinal_pattern is None
    assert columns["label"].measurement_levels == ["nominal"]


def test_boolean_vocabularies_and_native_booleans(store):
    content = b"satisfied,flag,answer\nyes,true,\xd9\x86\xd8\xb9\xd9\x85\nno,false,\xd9\x84\xd8\xa7\nyes,true,\xd9\x86\xd8\xb9\xd9\x85\n"
    columns = profile_of(store, "b.csv", content)
    assert columns["satisfied"].physical_type == "BOOLEAN"
    assert columns["satisfied"].boolean_vocabulary == ["false", "true"]
    assert columns["flag"].physical_type == "BOOLEAN"
    assert columns["flag"].boolean_vocabulary == ["false", "true"]
    assert columns["flag"].measurement_levels == ["nominal"]
    assert columns["answer"].boolean_vocabulary == ["لا", "نعم"]


def test_short_low_cardinality_values_are_codes(store):
    content = b"gender,city\nF,Riyadh\nM,Jeddah\nF,Riyadh\nM,Dammam\n"
    columns = profile_of(store, "c.csv", content)
    assert columns["gender"].codes == ["F", "M"]
    assert columns["city"].codes is None


def test_latitude_and_longitude_by_name_and_range(store):
    content = b"store,lat,lon,latitude_of_birth\nA,24.7,46.7,300\nB,21.5,39.2,400\n"
    columns = profile_of(store, "g.csv", content)
    assert columns["lat"].geographic_role == "latitude"
    assert columns["lat"].measurement_levels == ["interval", "continuous", "geographic"]
    assert columns["lon"].geographic_role == "longitude"
    assert columns["latitude_of_birth"].geographic_role is None


def test_coordinates_stored_as_text_with_dirty_values_are_geographic(store):
    rows = [f"{16 + i},{36 + i},words" for i in range(11)]
    content = "store_latitude,store_longitude,lat\n" + "\n".join(rows) + "\nRiyadh,unknown,words\n"
    source = store.save_upload("text_coordinates.csv", content.encode())
    store.import_csv(source.dataset_id)
    profile = compute_statistics(store, source)
    columns = {column.name: column for column in profile.columns}
    for name, role in (("store_latitude", "latitude"), ("store_longitude", "longitude")):
        assert columns[name].physical_type == "VARCHAR"
        assert columns[name].geographic_role == role
        assert columns[name].measurement_levels == ["nominal", "geographic"]
        assert f"{name}: coordinates stored as text; 1 values are not numbers." in profile.warnings
    assert columns["lat"].geographic_role is None


def test_place_name_columns_are_flagged(store):
    columns = profile_of(store, "p.csv", b"country,total\nSaudi Arabia,1\nEgypt,2\n")
    assert columns["country"].geographic_role == "place_name"
    assert columns["country"].measurement_levels == ["nominal", "geographic"]
    assert not columns["country"].values_omitted


def test_wkt_content_and_geometry_names_are_omitted(store):
    polygon = "POLYGON ((45 19, 46 20, 45 19))"
    content = f"region,boundary,the_geom\nRiyadh,\"{polygon}\",x\n".encode()
    columns = profile_of(store, "w.csv", content)
    assert columns["boundary"].values_omitted
    assert columns["boundary"].geographic_role == "wkt"
    assert columns["boundary"].measurement_levels == ["nominal", "geographic"]
    assert columns["boundary"].common_values == []
    assert columns["the_geom"].values_omitted
    assert columns["the_geom"].geographic_role == "wkt"
    assert not columns["region"].values_omitted


def test_geometry_named_numeric_column_is_omitted_without_statistics(store):
    columns = profile_of(store, "s.csv", b"district,shape_area\nA,12.5\nB,7.25\n")
    assert columns["shape_area"].values_omitted
    assert columns["shape_area"].numeric is None
    assert columns["shape_area"].measurement_levels == ["interval"]
    assert columns["shape_area"].geographic_role is None
    assert not columns["district"].values_omitted


def test_unique_values_are_neither_ordinal_nor_codes(store):
    columns = profile_of(store, "u.csv", b"order_id,code\no1,A\no2,B\no3,C\n")
    assert columns["order_id"].ordinal_pattern is None
    assert columns["order_id"].codes is None
    assert columns["order_id"].measurement_levels == ["nominal"]
    assert columns["code"].codes is None


def test_columns_beyond_the_detail_cap_send_metadata_only(store):
    from vis_agent.profiler.measurements import MAX_DETAILED_COLUMNS

    names = [f"c{i}" for i in range(MAX_DETAILED_COLUMNS + 3)]
    header = ",".join(names)
    rows = "\n".join(",".join(f"v{i}_{r}" for i in range(len(names))) for r in range(3))
    source = store.save_upload("wide.csv", f"{header}\n{rows}\n".encode())
    store.import_csv(source.dataset_id)
    profile = compute_statistics(store, source)
    columns = {column.name: column for column in profile.columns}
    assert len(columns) == len(names)
    assert columns["c0"].values_omitted is False and columns["c0"].common_values
    for name in names[MAX_DETAILED_COLUMNS:]:
        assert columns[name].values_omitted is True
        assert columns[name].common_values == []
        assert columns[name].measurement_levels == ["nominal"]
        assert columns[name].null_count == 0 and columns[name].distinct_count == 3
    assert set(profile.sample_rows[0]) == set(names[:MAX_DETAILED_COLUMNS])
    assert any("3 more columns" in warning for warning in profile.warnings)


def test_timezone_aware_timestamps_profile(store):
    content = b"at,value\n2026-01-01 10:00:00+03,1\n2026-01-02 11:30:00+03,2\n"
    columns = profile_of(store, "tz.csv", content)
    assert columns["at"].physical_type.startswith("TIMESTAMP")
    assert columns["at"].measurement_levels == ["time"]
    assert columns["at"].earliest is not None


def test_place_name_hint_covers_more_words_and_arabic(store):
    header = "municipality,entry_port,airport_name,المنطقة,البلدية,city_size_category,transport_mode,total"
    rows = ["Diriyah,KKIA,King Khalid,منطقة الرياض,الدرعية,small,bus,1", "Riyadh,KAIA,King Abdulaziz,منطقة مكة,جدة,large,car,2"]
    columns = profile_of(store, "places.csv", ("\n".join([header] + rows) + "\n").encode())
    for name in ("municipality", "entry_port", "airport_name", "المنطقة", "البلدية"):
        assert columns[name].geographic_role == "place_name", name
    for name in ("city_size_category", "transport_mode"):
        assert columns[name].geographic_role is None, name
    assert columns["total"].geographic_role is None


def test_ordered_levels_in_words_are_ordinal(store):
    content = "wealth,size_ar,label\nPoor,صغير,alpha\nMiddle,متوسط,beta\nRich,كبير,gamma\nPoor,صغير,alpha\nUpper Middle,متوسط,delta\nLower Middle,كبير,alpha\n"
    columns = profile_of(store, "levels.csv", content.encode("utf-8"))
    assert columns["wealth"].measurement_levels == ["nominal", "ordinal"]
    assert columns["wealth"].ordinal_pattern == "poor < lower middle < middle < upper middle < rich"
    assert columns["size_ar"].ordinal_pattern == "صغير < متوسط < كبير"
    assert columns["label"].ordinal_pattern is None
    assert columns["label"].measurement_levels == ["nominal"]


def test_numeric_bands_in_words_are_ordinal(store):
    rows = [
        "أعلى من 4,over 60,18-35",
        "أقل من 4,18-35,Riyadh",
        "أعلى من 4,under 18,18-35",
        "أقل من 4,36-60,Riyadh",
    ] * 2
    content = "gpa_group,age_group,mixed\n" + "\n".join(rows) + "\n"
    columns = profile_of(store, "bands.csv", content.encode())
    assert columns["gpa_group"].ordinal_pattern == "أقل من 4 < أعلى من 4"
    assert columns["age_group"].ordinal_pattern == "under 18 < 18-35 < 36-60 < over 60"
    for name in ("gpa_group", "age_group"):
        assert "ordinal" in columns[name].measurement_levels
    assert "ordinal" not in columns["mixed"].measurement_levels
    assert columns["mixed"].ordinal_pattern is None


def test_small_integer_sequences_named_like_ranks_are_ordinal(store):
    rows = [f"{i % 3 + 1},{i % 3 + 1},{i + 1}" for i in range(9)]
    content = "sequence_number,amount,rank\n" + "\n".join(rows) + "\n"
    columns = profile_of(store, "sequences.csv", content.encode())
    assert columns["sequence_number"].measurement_levels == ["interval", "discrete", "ordinal"]
    assert columns["sequence_number"].ordinal_pattern == "1 < 2 < 3"
    assert columns["amount"].measurement_levels == ["interval", "discrete"]
    assert "ordinal" not in columns["rank"].measurement_levels


def test_word_scales_need_no_repeats_and_cover_education(store):
    content = "wealth,qualification\nRich,دكتوراه\nUpper Middle,بكالوريوس\nPoor,دبلوم عالي\n"
    columns = profile_of(store, "education.csv", content.encode())
    assert columns["wealth"].ordinal_pattern == "poor < upper middle < rich"
    assert columns["qualification"].ordinal_pattern == "بكالوريوس < دبلوم عالي < دكتوراه"
    for name in ("wealth", "qualification"):
        assert "ordinal" in columns[name].measurement_levels

    columns = profile_of(store, "single_level.csv", b"level\nLower Middle\n")
    assert columns["level"].ordinal_pattern == "lower middle"
    assert "ordinal" in columns["level"].measurement_levels

    columns = profile_of(store, "invoices.csv", b"code\nINV-1\nINV-2\nINV-3\n")
    assert columns["code"].ordinal_pattern is None


@pytest.mark.parametrize("values,earliest,latest", [
    (["1447-03-12", "1446-12-30"], "1446-12-30", "1447-03-12"),
    (["١٤٤٧/٠٣/١٢", "١٤٤٦/١٢/٣٠"], "1446/12/30", "1447/03/12"),
    (["12 ربيع الأول 1447", "٣٠ رمضان ١٤٤٦"], None, None),
    (["١٤٤٧", "١٣٨٣"], "1383", "1447"),
    (["1447-03", "1446/12"], None, None),
])
def test_hijri_forms_have_translated_text_ranges(store, values, earliest, latest):
    columns = profile_of(store, "hijri.csv", ("day\n" + "\n".join(values) + "\n").encode())
    day = columns["day"]
    assert "hijri" in day.measurement_levels
    assert day.earliest == earliest
    assert day.latest == latest
    assert day.ordinal_pattern is None


@pytest.mark.parametrize("month", [
    "محرم", "صفر", "ربيع الأول", "ربيع الآخر", "ربيع الثاني", "جمادى الأولى", "جمادى الآخرة",
    "جمادى الثانية", "رجب", "شعبان", "رمضان", "شوال", "ذو القعدة", "ذي القعدة", "ذو الحجة", "ذي الحجة",
])
def test_hijri_month_names(store, month):
    columns = profile_of(store, "month.csv", f"day\n1 {month} 1447\n".encode())
    assert "hijri" in columns["day"].measurement_levels


@pytest.mark.parametrize("value", ["1299/12/30", "1500/01/01", "1447/13/01", "1447/01/31", "0 محرم 1447"])
def test_invalid_hijri_text_is_not_hijri(store, value):
    columns = profile_of(store, "invalid.csv", f"day\n{value}\n".encode())
    assert "hijri" not in columns["day"].measurement_levels


def test_gregorian_dates_are_not_hijri(store):
    columns = profile_of(store, "gregorian.csv", b"day\n2026-03-12\n2026-04-13\n")
    assert columns["day"].measurement_levels == ["time"]


@pytest.mark.parametrize("name", ["year_hijri", "العام_الهجري", "year_h", "YEAR_H"])
def test_hijri_integer_years_with_name_hint(store, name):
    columns = profile_of(store, "years.csv", f"{name}\n1300\n1383\n1447\n1500\n".encode())
    year = columns[name]
    assert year.physical_type == "BIGINT"
    assert "hijri" in year.measurement_levels
    assert (year.earliest, year.latest) == ("1300", "1500")


@pytest.mark.parametrize("header,rows", [
    ("year,day", "1383,1963-06-01\n1447,2026-01-01"),
    ("day,year", "1963-06-01,1383\n2026-01-01,1447"),
    ("year,day", "1383,1963-06-01 12:00:00\n1447,2026-01-01 12:00:00"),
])
def test_hijri_integer_years_with_gregorian_companion_in_either_order(store, header, rows):
    columns = profile_of(store, "companion.csv", f"{header}\n{rows}\n".encode())
    assert "hijri" in columns["year"].measurement_levels
    assert (columns["year"].earliest, columns["year"].latest) == ("1383", "1447")


def test_a_measure_beside_a_gregorian_date_is_not_a_hijri_year(store):
    columns = profile_of(store, "amounts.csv", b"day,amount\n2026-01-01,1400\n2026-02-01,1447\n")
    assert "hijri" not in columns["amount"].measurement_levels
    assert columns["amount"].measurement_levels == ["interval", "discrete"]


@pytest.mark.parametrize("content", [
    "code\n1383\n1447\n",
    "year_h\n1299\n1447\n",
    "year_h\n1447\n1501\n",
    "year_h\n1383.0\n1447.0\n",
    "year,day\n1383,1900-01-01\n1447,2026-01-01\n",
    "year,day\n1383,1446-01-01\n1447,1447-01-01\n",
    "year,day\n1383,10:00:00\n1447,11:00:00\n",
])
def test_integer_year_detection_requires_range_and_context(store, content):
    columns = profile_of(store, "not_hijri.csv", content.encode())
    assert "hijri" not in next(iter(columns.values())).measurement_levels


def test_arabic_digit_measure_has_all_numeric_statistics(store):
    columns = profile_of(store, "amounts.csv", "amount\n٣٬٤٥٦٫٥\n-١٢٫٥\n١٠٠\n".encode())
    amount = columns["amount"]
    assert amount.physical_type == "VARCHAR"
    assert amount.measurement_levels == ["interval", "continuous", "arabic_digits"]
    assert amount.integer_valued is False
    assert amount.numeric.model_dump() == pytest.approx({
        "finite_count": 3, "non_finite_count": 0, "minimum": -12.5, "maximum": 3456.5,
        "mean": 1181.3333333333333, "standard_deviation": 1609.4412246352942,
        "q25": 43.75, "median": 100, "q75": 1778.25,
    })


@pytest.mark.parametrize("valid_count,expected", [(9, True), (8, False)])
def test_localized_threshold_uses_non_null_values(store, valid_count, expected):
    rows = ["١٤٤٧/٠٣/١٢,٣٬٤٥٦٫٥"] * valid_count + ["unknown,unknown"] * (10 - valid_count) + [","]
    columns = profile_of(store, "threshold.csv", ("day,amount\n" + "\n".join(rows) + "\n").encode())
    assert ("hijri" in columns["day"].measurement_levels) is expected
    assert ("arabic_digits" in columns["amount"].measurement_levels) is expected
    assert "arabic_digits" not in columns["day"].measurement_levels
    assert "hijri" not in columns["amount"].measurement_levels
    if expected:
        assert columns["amount"].numeric.minimum == 3456.5
        assert columns["amount"].numeric.maximum == 3456.5
        assert columns["amount"].numeric.finite_count == 9
        assert columns["amount"].numeric.non_finite_count == 1
    else:
        assert columns["amount"].numeric is None


def test_localized_detection_preserves_omitted_value_protection(store):
    rows = ["١٤٤٧/٠٣/١٢,١٢٫٥,١٢٫٥"] * 9 + [f"{'x' * 257},١٢٫٥,POINT(1 2)"]
    columns = profile_of(store, "omitted.csv", ("day,shape_area,amount\n" + "\n".join(rows) + "\n").encode())
    for column in columns.values():
        assert column.values_omitted
        assert not {"hijri", "arabic_digits"}.intersection(column.measurement_levels)
        assert column.earliest is None and column.latest is None and column.numeric is None


def test_null_columns_do_not_get_localized_levels(store):
    columns = profile_of(store, "nulls.csv", b"year_h,amount,day\n,,\n,,\n")
    for column in columns.values():
        assert not {"hijri", "arabic_digits"}.intersection(column.measurement_levels)
