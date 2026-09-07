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
