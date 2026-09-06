from measurements import compute_statistics


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
    content = b"quarter,week,label\nQ1,Week 1,alpha\nQ2,Week 2,beta\nQ3,Week 10,gamma\nQ4,Week 11,delta\n"
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
