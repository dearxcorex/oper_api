import json
from datetime import date
from pathlib import Path

import pytest

from nbtc_oper import build_query, build_station_query, parse, places, station_key
from nbtc_oper.dates import from_dotnet_date, from_portal_date, to_portal_date

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------- dates ----------

def test_dates_round_trip_buddhist_era():
    assert to_portal_date("2026-01-01") == "01/01/2569"
    assert to_portal_date(date(2026, 1, 28)) == "28/01/2569"
    assert to_portal_date("01/01/2569") == "01/01/2569"
    assert to_portal_date(None) == ""
    assert from_portal_date("28/01/2569") == "2026-01-28"


def test_unset_portal_date_is_none():
    assert from_portal_date("01/01/2443") is None
    assert from_portal_date("") is None


def test_dotnet_date():
    assert from_dotnet_date("/Date(1595523600000)/") == "2020-07-24T00:00:00+07:00"
    assert from_dotnet_date(None) is None


# ---------- search ----------

def test_search_page_totals_and_paging():
    page = parse.parse_search_page(fixture("search_page.html"))
    assert page["total"] == 120
    assert page["pages"] == 6
    assert len(page["rows"]) == 20


def test_search_row_is_typed_and_keeps_raw():
    row = parse.parse_search_page(fixture("search_page.html"))["rows"][0]
    assert row["chk_id"] == 52390
    assert row["no"] == 1
    assert row["recorded_date"] == "2026-02-02"
    assert row["inspected_date"] == "2026-01-28"
    assert row["area"] == "เขต 23"
    assert row["station_code"] == "RFXL680853"
    assert row["station_name"] == "แฟมิลี่ เรดิโอ"
    assert row["frequency_mhz"] == 93.25
    assert row["licence_no"] == "BF-S10033-0424-68"
    assert (row["province"], row["district"], row["subdistrict"]) == (
        "ชัยภูมิ", "เมืองชัยภูมิ", "ในเมือง",
    )
    assert row["result"] == "ตรงตามมาตรฐาน"
    assert row["instrument"] == "H-R&S-FSH8"
    assert row["warning_doc_no"] is None and row["warning_doc_date"] is None
    assert row["status"] == "อนุมัติแล้ว"
    assert row["raw"]["จังหวัด"] == "จ.ชัยภูมิ"


def test_every_search_row_has_the_same_keys():
    rows = parse.parse_search_page(fixture("search_page.html"))["rows"]
    assert len({r["chk_id"] for r in rows}) == 20
    assert all(r.keys() == rows[0].keys() for r in rows)
    assert len(rows[0]) == 19  # chk_id + 16 columns (warning doc splits in two) + raw


def test_page_without_results():
    page = parse.parse_search_page("<html><body><p>nothing</p></body></html>")
    assert page == {"total": None, "pages": 1, "rows": []}


def test_login_page_detection():
    login = '<form id="Login"><input id="UserName"><button id="bLogin"></button></form>'
    assert parse.is_login_page(login)
    assert not parse.is_login_page(fixture("search_page.html"))


def test_build_query_matches_the_portals_own_url():
    query = dict(build_query(inspected_from="2026-01-01"))
    assert query["FDt"] == "01/01/2569"
    assert (query["RegID"], query["AreaID"], query["StnTypeID"]) == ("5", "8", "4")
    assert (query["sProv1"], query["sAumphoe1"], query["sTambol1"]) == ("0", "0", "0")
    assert query["TDt"] == "" and query["StaChk"] == ""
    assert dict(build_query(unlicensed_only=True))["StaChk"] == "N"


def test_station_key_falls_back_when_a_row_has_no_code():
    coded = {"station_code": "RFXL680853", "station_name": "a", "frequency_mhz": 93.25}
    again = {"station_code": "RFXL680853", "station_name": "renamed", "frequency_mhz": 93.25}
    assert station_key(coded) == station_key(again)
    one = {"station_code": None, "station_name": "a", "frequency_mhz": 90.0, "licence_no": None}
    other = {"station_code": None, "station_name": "b", "frequency_mhz": 90.0, "licence_no": None}
    assert station_key(one) != station_key(other)
    assert station_key(one) == station_key(dict(one))


# ---------- detail ----------

def test_detail_page_core_fields():
    detail = parse.parse_detail_page(fixture("detail_page.html"), 52390)
    assert detail["chk_id"] == 52390
    assert detail["stn_id"] == 19363
    assert detail["region"] == "ภาค 2"
    assert detail["area"] == "เขต 23"
    assert detail["source_type"] == "ตรวจตามแผน"
    assert detail["measured_frequency"] == 93.25
    assert detail["measured_frequency_unit"] == "MHz"
    assert detail["power"] == 500
    assert detail["antenna_height"] == 60
    assert detail["result"] == "ตรงตามมาตรฐาน"
    assert detail["inspected_date"] == "2026-01-28"
    assert detail["reported_date"] == "2026-02-02"
    assert detail["approved_date"] == "2026-02-02"
    assert detail["warning_doc_date"] is None  # portal's 01/01/2443 placeholder
    assert detail["action"] is None  # unselected dropdown
    assert len(detail["inspectors"]) == 2
    assert detail["raw"]["DetPow"] == "500"
    assert "__VIEWSTATE" not in detail["raw"]


# ---------- station ----------

def test_station_record():
    station = parse.shape_station(json.loads(fixture("station.json")))
    assert station["stn_id"] == 22959
    assert station["station_id"] == "05520415"
    assert station["nbtc_code"] is None
    assert station["frequency_mhz"] == 92.25
    assert (station["lat"], station["lng"]) == (16.12671, 101.897369)
    assert station["licence_expires"] is None
    assert station["raw"]["SrcData"] == "OPER"


def test_station_code_systems_are_split_on_shape():
    relicensed = parse.shape_station({"StnCode": "RFXL681523", "stationId": ""})
    assert (relicensed["nbtc_code"], relicensed["station_id"]) == ("RFXL681523", None)
    legacy = parse.shape_station({"StnCode": "05540021", "stationId": ""})
    assert (legacy["nbtc_code"], legacy["station_id"]) == (None, "05540021")
    swapped = parse.shape_station({"StnCode": "RFXL680853", "stationId": "RFXL680853"})
    assert (swapped["nbtc_code"], swapped["station_id"]) == ("RFXL680853", None)


# ---------- station search ----------

def test_station_search_page_totals_and_paging():
    page = parse.parse_station_search_page(fixture("station_search_page.html"))
    assert page["total"] == 282
    assert page["pages"] == 15
    assert len(page["rows"]) == 20
    assert len({r["stn_id"] for r in page["rows"]}) == 20
    assert all(r.keys() == page["rows"][0].keys() for r in page["rows"])


def test_station_search_row_is_typed_and_keeps_raw():
    rows = parse.parse_station_search_page(fixture("station_search_page.html"))["rows"]
    assert rows[0]["stn_id"] == 292727
    assert rows[0]["source"] == "BCS"
    assert rows[0]["station_code"] is None and rows[0]["frequency_mhz"] is None
    row = rows[1]
    assert row["stn_id"] == 16168
    assert row["no"] == 2
    assert row["station_type"] == "สถานีวิทยุกระจายเสียง"
    assert row["station_subtype"] == "สถานีวิทยุทดลอง"
    assert row["station_code"] == "05520395"
    assert row["name"] == "ข้าวเหนียวเรดิโอ"
    assert row["frequency_mhz"] == 90.5
    assert row["source"] == "OPER"
    assert row["raw"]["ความถี่"] == "90.50MHz"


def test_station_search_page_without_results():
    page = parse.parse_station_search_page("<html><body><p>nothing</p></body></html>")
    assert page == {"total": None, "pages": 1, "rows": []}


def test_station_search_offers_its_areas_provinces():
    html = fixture("station_search_page.html")
    assert parse.station_search_provinces(html) == ["31", "30", "36"]
    assert parse.station_search_provinces("<html></html>") == []


def test_build_station_query_matches_the_portals_own_url():
    query = dict(build_station_query(source="OPER", province_id="36"))
    assert (query["AreaID"], query["StnTypeID"], query["ff"]) == ("8", "4", "11")
    assert (query["sProv1"], query["sAumphoe1"], query["SrcData"]) == ("36", "0", "OPER")
    assert query["StnName"] == "" and query["Freq"] == ""


# ---------- form options ----------

def test_form_options_tables():
    options = parse.parse_form_options(fixture("add_form_selects.html"))
    assert options["regions"] == [{"id": 5, "name": "ภาค 2"}]
    assert options["areas"] == [{"id": 8, "name": "เขต 23", "region_id": 5}]
    assert {o["id"] for o in options["source_types"]} == {2, 3}
    assert len(options["issues"]) == 14
    assert len(options["antennas"]) == 67
    assert len(options["cables"]) == 6
    assert len(options["test_equipment"]) == 632
    assert {"id": 214493, "name": "R-TCI-Chaiyaphum", "area_id": 8} in options["test_equipment"]
    assert len(options["inspectors"]) == 427
    assert len(options["approvers"]) == 80


def test_form_options_skip_placeholders():
    options = parse.parse_form_options(fixture("add_form_selects.html"))
    names = [o["name"] for table in options.values() for o in table]
    assert "กรุณาเลือก" not in names
    assert all(o["id"] not in (0, "", "0") for table in options.values() for o in table)


# ---------- find_stations ----------

def test_split_location_takes_the_last_place_named():
    loc = "7 หมู่ 3 ต.บ้านแก้ง อ.แก้งคร้อ ชัยภูมิ 36150 ต.บ้านแก้ง อ.ภูเขียว จ.ชัยภูมิ"
    assert parse.split_location(loc) == {
        "subdistrict": "บ้านแก้ง", "district": "ภูเขียว", "province": "ชัยภูมิ",
    }
    assert parse.split_location(None) == {"subdistrict": None, "district": None, "province": None}


def test_compact_station_has_no_coordinates_or_raw():
    row = parse.parse_station_search_page(fixture("station_search_page.html"))["rows"][0]
    record = parse.shape_station(json.loads(fixture("station.json")))
    out = parse.compact_station(row, record)
    assert "raw" not in out and "lat" not in out and "lng" not in out
    assert out["stn_id"] == row["stn_id"]
    assert {"licence_no", "operator", "district", "province"} <= out.keys()


def test_find_stations_tool_maps_onto_find_stations():
    import inspect
    from nbtc_oper import NbtcOper
    from nbtc_oper.llm import FIND_STATIONS_TOOL

    params = inspect.signature(NbtcOper.find_stations).parameters
    assert set(FIND_STATIONS_TOOL["input_schema"]["properties"]) <= set(params)


# ---------- places ----------

@pytest.fixture(scope="module")
def gazetteer():
    return places.parse_dpv(fixture("dpv_sample.js"))


def test_places_resolve_names_with_or_without_prefix(gazetteer):
    assert places.resolve(gazetteer, "นครราชสีมา") == ("30", "0", "0")
    assert places.resolve(gazetteer, "จ.ชัยภูมิ", "อ.เมืองชัยภูมิ") == ("36", "3601", "0")
    assert places.resolve(gazetteer, "ชัยภูมิ", "เมืองชัยภูมิ", "ในเมือง") == ("36", "3601", "360101")
    assert places.resolve(gazetteer, "กรุงเทพมหานคร", "คลองเตย")[1] == "1033"


def test_district_alone_finds_its_province(gazetteer):
    provinces = places.provinces_with_district(gazetteer, "อ.ภูเขียว")
    assert [gazetteer["provinces"][p] for p in provinces] == ["จ.ชัยภูมิ"]


def test_places_accept_codes_and_reject_unknown_names(gazetteer):
    assert places.resolve(gazetteer, 36, "3601") == ("36", "3601", "0")
    assert places.resolve(gazetteer) == ("0", "0", "0")
    with pytest.raises(places.UnknownPlace):
        places.resolve(gazetteer, "ไม่มีจริง")
    with pytest.raises(places.UnknownPlace):
        places.resolve(gazetteer, None, "เมืองชัยภูมิ")
