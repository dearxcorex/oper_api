from nbtc_oper.api import NbtcOper

PASS, FAIL = "ตรงตามมาตรฐาน", "ไม่ตรงตามมาตรฐาน"


class FakeSearch(NbtcOper):
    def __init__(self, rows, total=None):
        self.rows, self.total, self.filters = rows, total, None

    def search(self, *, fresh=False, **filters):
        self.filters = filters
        total = len(self.rows) if self.total is None else self.total
        return {"total": total, "rows": self.rows, "complete": len(self.rows) >= total}


def row(code, result):
    return {"station_code": code, "result": result}


def test_count_splits_inspections_and_stations_by_result():
    api = FakeSearch([row("A", PASS), row("A", PASS), row("B", PASS), row("C", FAIL), row("A", FAIL)])
    counted = api.count_stations(inspected_from="2026-01-01")
    counted_list = counted["station_list"]
    assert [(s["station_code"], s["inspections"]) for s in counted_list] == [("A", 3), ("B", 1), ("C", 1)]
    assert counted == {
        "inspections": 5,
        "stations": 3,
        "by_result": {
            PASS: {"inspections": 3, "stations": 2},
            FAIL: {"inspections": 2, "stations": 2},
        },
        "complete": True,
        "station_list": counted_list,
        "truncated": False,
    }


def test_count_leaves_the_result_filter_to_the_portal():
    api = FakeSearch([row("A", PASS)])
    api.count_stations(inspected_from="2026-01-01", result=PASS)
    assert api.filters == {"inspected_from": "2026-01-01", "result": PASS}


def test_inspections_is_the_portal_total_even_when_rows_are_missing():
    api = FakeSearch([row("A", PASS)], total=2)
    counted = api.count_stations()
    assert (counted["inspections"], counted["complete"]) == (2, False)


def inspected(code, name, day, result):
    return {"station_code": code, "station_name": name, "inspected_date": day, "result": result,
            "province": "ชัยภูมิ", "raw": {"x": 1}}


def test_station_list_names_each_station_by_its_latest_inspection():
    api = FakeSearch([
        inspected("A", "สถานี เอ", "2026-01-05", FAIL),
        inspected("B", "สถานี บี", "2026-03-01", FAIL),
        inspected("A", "สถานี เอ", "2026-02-10", PASS),
    ])
    listed = api.count_stations()["station_list"]
    assert [(s["station_name"], s["inspected_date"], s["result"], s["inspections"]) for s in listed] == [
        ("สถานี บี", "2026-03-01", FAIL, 1),
        ("สถานี เอ", "2026-02-10", PASS, 2),
    ]
    assert "raw" not in listed[0]


def test_station_list_stops_at_the_limit():
    api = FakeSearch([inspected(c, c, f"2026-01-0{i + 1}", FAIL) for i, c in enumerate("ABC")])
    counted = api.count_stations(limit=2)
    assert [s["station_code"] for s in counted["station_list"]] == ["C", "B"]
    assert (counted["stations"], counted["truncated"]) == (3, True)
