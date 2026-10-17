"""งานคุ้มครอง: content and advertising inspections (FF28ChkSch.aspx)."""

from pathlib import Path

import pytest

from nbtc_oper import parse
from nbtc_oper.api import NbtcOper, build_content_query

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------- parsing ----------

def test_content_page_totals_and_paging():
    page = parse.parse_content_search_page(fixture("content_search_page.html"))
    assert (page["total"], page["pages"], len(page["rows"])) == (211, 11, 20)


def test_content_row_fields():
    first = parse.parse_content_search_page(fixture("content_search_page.html"))["rows"][0]
    assert {k: v for k, v in first.items() if k != "raw"} == {
        "chk_id": first["chk_id"],
        "no": 1,
        "inspected_date": "2026-01-20",
        "region": "ภาค 2",
        "area": "เขต 23",
        "licensee": "บริษัท อสมท จำกัด (มหาชน)",
        "station_code": "RFYN650027",
        "station_name": "สถานีวิทยุ บมจ.อสมท จังหวัดนครราชสีมา",
        "province": "นครราชสีมา",
        "district": "เมืองนครราชสีมา",
        "subdistrict": "บ้านโพธิ์",
        "location": first["location"],
        "frequency_mhz": 95.75,
        "programme": "ธนาพรดีไลน์",
        "result": "ไม่พบการกระทำผิด",
        "instrument": "P-R&S-ESME, IC RECORDER, Video Record",
        "process": None,
        "status": "อนุมัติแล้ว",
    }
    assert isinstance(first["chk_id"], int)


def test_content_violations_page_keeps_result_and_follow_up_step():
    rows = parse.parse_content_search_page(fixture("content_search_violations.html"))["rows"]
    assert {r["result"] for r in rows} == {"เนื้อหาโฆษณา ผลิตภัณฑ์สมุนไพร"}
    assert [r["process"] for r in rows].count("ส่ง สสจ.") == 1


# ---------- query ----------

def test_content_query_is_what_the_portal_form_sends():
    query = build_content_query(
        inspected_from="2026-01-01", freq_from="88.00", freq_to="88.00", result_id=17, source_type_id=2
    )
    assert query == [
        ("RegID", "5"), ("AreaID", "8"), ("AreaID_raw", "0"), ("SrcTypeID", "2"),
        ("sProv1", "0"), ("sAumphoe1", "0"), ("sTambol1", "0"), ("ChkResuID", "17"),
        ("Process", ""), ("Doc03", ""), ("RemChkNa", ""), ("StaNa", ""),
        ("FreqMhz1", "88.00"), ("FreqMhz2", "88.00"), ("ZipCode", ""),
        ("FDt", "01/01/2569"), ("TDt", ""), ("FDtC", ""), ("TDtC", ""),
        ("SiteCode", ""), ("ProgNa", ""),
    ]


def test_content_query_defaults_to_every_source_type_and_result():
    query = dict(build_content_query())
    assert (query["SrcTypeID"], query["ChkResuID"]) == ("0", "0")


# ---------- grouping ----------

CLEAN, OFF_AIR, HERBAL = "ไม่พบการกระทำผิด", "ไม่พบการออกอากาศ", "เนื้อหาโฆษณา ผลิตภัณฑ์สมุนไพร"


class FakeContent(NbtcOper):
    def __init__(self, rows, total=None):
        self.rows, self.total, self.filters = rows, total, None

    def content_search(self, *, fresh=False, **filters):
        self.filters = filters
        total = len(self.rows) if self.total is None else self.total
        return {"total": total, "rows": self.rows, "complete": len(self.rows) >= total}


def checked(code, day, result, programme="รายการ", process=None, chk_id=1):
    return {
        "chk_id": chk_id, "station_code": code, "station_name": f"สถานี {code}", "frequency_mhz": 88.0,
        "licensee": "ผู้รับใบอนุญาต", "province": "นครราชสีมา", "district": "เมือง", "subdistrict": "ใน",
        "location": "ที่อยู่", "inspected_date": day, "result": result, "programme": programme,
        "process": process, "status": "อนุมัติแล้ว", "instrument": "ESME", "raw": {"x": 1},
    }


def test_groups_by_station_newest_first_with_date_and_result_side_by_side():
    api = FakeContent([
        checked("A", "2026-03-10", CLEAN, chk_id=1),
        checked("B", "2026-05-05", CLEAN, chk_id=2),
        checked("A", "2026-09-04", OFF_AIR, chk_id=3),
    ])
    found = api.content_inspections(inspected_from="2026-01-01", frequency=88)
    assert [s["station_code"] for s in found["station_list"]] == ["A", "B"]
    a = found["station_list"][0]
    assert a["checks"] == [
        {"inspected_date": "2026-09-04", "result": OFF_AIR, "programme": "รายการ", "process": None,
         "status": "อนุมัติแล้ว", "chk_id": 3},
        {"inspected_date": "2026-03-10", "result": CLEAN, "programme": "รายการ", "process": None,
         "status": "อนุมัติแล้ว", "chk_id": 1},
    ]
    assert (a["inspections"], a["latest_date"], a["flagged"]) == (2, "2026-09-04", False)
    assert "location" not in a and "instrument" not in a and "raw" not in a
    assert found["inspections"] == 3 and found["stations"] == 2
    assert found["by_result"] == {CLEAN: 2, OFF_AIR: 1}
    assert api.filters["freq_from"] == api.filters["freq_to"] == "88.00"


def test_flagged_stations_come_first():
    api = FakeContent([
        checked("A", "2026-09-01", CLEAN),
        checked("B", "2026-02-01", HERBAL, process="ส่ง สสจ."),
    ])
    listed = api.content_inspections(inspected_from="2026-01-01")["station_list"]
    assert [(s["station_code"], s["flagged"]) for s in listed] == [("B", True), ("A", False)]


def test_a_result_label_goes_to_the_portal_as_its_code():
    api = FakeContent([checked("B", "2026-02-01", HERBAL)])
    api.content_inspections(inspected_from="2026-01-01", result=HERBAL, source_type="เรื่องร้องเรียน")
    assert (api.filters["result_id"], api.filters["source_type_id"]) == (17, 1)


def test_any_violation_is_filtered_here_because_the_portal_cannot():
    api = FakeContent([
        checked("A", "2026-09-01", CLEAN),
        checked("B", "2026-02-01", HERBAL),
        checked("C", "2026-02-02", OFF_AIR),
    ], total=3)
    found = api.content_inspections(inspected_from="2026-01-01", result="พบการกระทำผิด")
    assert api.filters["result_id"] == 0
    assert [s["station_code"] for s in found["station_list"]] == ["B"]
    assert (found["inspections"], found["stations"], found["complete"]) == (1, 1, True)


def test_unknown_labels_are_refused():
    with pytest.raises(ValueError):
        FakeContent([]).content_inspections(result="ผิดแน่ๆ")
    with pytest.raises(ValueError):
        FakeContent([]).content_inspections(source_type="ไม่มี")


def test_dates_default_to_the_first_of_january_this_year(monkeypatch):
    api = FakeContent([])
    monkeypatch.setattr("nbtc_oper.api.bangkok_today", lambda: __import__("datetime").date(2026, 10, 17))
    found = api.content_inspections()
    assert api.filters["inspected_from"] == "2026-01-01"
    assert (found["inspected_from"], found["inspected_to"]) == ("2026-01-01", None)


def test_station_list_stops_at_the_limit():
    api = FakeContent([checked(c, f"2026-01-0{i + 1}", CLEAN) for i, c in enumerate("ABC")])
    found = api.content_inspections(inspected_from="2026-01-01", limit=2)
    assert [s["station_code"] for s in found["station_list"]] == ["C", "B"]
    assert (found["stations"], found["truncated"]) == (3, True)


def test_a_blank_result_is_not_a_violation():
    api = FakeContent([checked("A", "2026-09-01", None)])
    assert api.content_inspections(inspected_from="2026-01-01")["station_list"][0]["flagged"] is False
    assert api.content_inspections(inspected_from="2026-01-01", result="พบการกระทำผิด")["stations"] == 0


# ---------- LLM tool ----------

def test_content_tool_maps_onto_content_inspections():
    import inspect
    from nbtc_oper.api import ANY_VIOLATION, CONTENT_RESULTS, CONTENT_SOURCE_TYPES
    from nbtc_oper.llm import CONTENT_INSPECTIONS_TOOL

    props = CONTENT_INSPECTIONS_TOOL["input_schema"]["properties"]
    assert set(props) <= set(inspect.signature(NbtcOper.content_inspections).parameters)
    assert props["result"]["enum"] == [*CONTENT_RESULTS, ANY_VIOLATION]
    assert props["source_type"]["enum"] == list(CONTENT_SOURCE_TYPES)


def test_run_tool_dispatches_find_content_inspections():
    from nbtc_oper.llm import run_tool

    class Api:
        def content_inspections(self, **kwargs):
            return kwargs

    args = {"frequency": 88.0}
    assert run_tool(Api(), "find_content_inspections", args) == args


def test_each_inspection_tool_names_its_work_and_asks_when_unclear():
    from nbtc_oper.llm import CONTENT_INSPECTIONS_TOOL, COUNT_INSPECTIONS_TOOL, FIND_STATIONS_TOOL

    content, checks = CONTENT_INSPECTIONS_TOOL["description"], COUNT_INSPECTIONS_TOOL["description"]
    assert "งานคุ้มครอง" in content and "not งานตรวจสอบ" in content
    assert "งานตรวจสอบ" in checks and "not งานคุ้มครอง" in checks
    for description in (content, checks):
        assert "ask" in description and "งานตรวจสอบ หรือ งานคุ้มครอง" in description
    assert "งานคุ้มครอง" not in FIND_STATIONS_TOOL["description"]


# ---------- CLI ----------

def test_cli_content_prints_the_grouped_answer(monkeypatch, capsys):
    import json
    from nbtc_oper import cli

    calls = []

    class Api:
        requests_sent = 0

        def __init__(self, **_):
            pass

        def content_inspections(self, **kwargs):
            calls.append(kwargs)
            return {"work": "งานคุ้มครอง", "station_list": []}

    monkeypatch.setattr(cli, "NbtcOper", Api)
    assert cli.main(["-o", "-", "content", "--frequency", "88", "--result", "พบการกระทำผิด"]) == 0
    assert json.loads(capsys.readouterr().out)["work"] == "งานคุ้มครอง"
    assert calls == [{"frequency": 88.0, "result": "พบการกระทำผิด", "limit": 25, "fresh": False}]


def test_stations_without_a_code_are_told_apart_by_licensee():
    a, b = checked(None, "2026-02-01", CLEAN), checked(None, "2026-02-02", CLEAN)
    b["licensee"] = "อีกราย"
    assert FakeContent([a, b]).content_inspections(inspected_from="2026-01-01")["stations"] == 2


def test_the_ask_rule_names_the_thai_cue_words():
    from nbtc_oper.llm import WHICH_WORK

    for word in ("กำลังส่ง", "ใบอนุญาต", "หนังสือเตือน", "เนื้อหา", "โฆษณา", "รายการ"):
        assert word in WHICH_WORK


def test_date_objects_come_back_as_iso():
    from datetime import date

    api = FakeContent([])
    found = api.content_inspections(inspected_from=date(2026, 1, 1), inspected_to=date(2026, 10, 16))
    assert (found["inspected_from"], found["inspected_to"]) == ("2026-01-01", "2026-10-16")
    assert api.filters["inspected_from"] == "2026-01-01"
