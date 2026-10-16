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
    assert api.count_stations(inspected_from="2026-01-01") == {
        "inspections": 5,
        "stations": 3,
        "by_result": {
            PASS: {"inspections": 3, "stations": 2},
            FAIL: {"inspections": 2, "stations": 2},
        },
        "complete": True,
    }


def test_count_leaves_the_result_filter_to_the_portal():
    api = FakeSearch([row("A", PASS)])
    api.count_stations(inspected_from="2026-01-01", result=PASS)
    assert api.filters == {"inspected_from": "2026-01-01", "result": PASS}


def test_inspections_is_the_portal_total_even_when_rows_are_missing():
    api = FakeSearch([row("A", PASS)], total=2)
    counted = api.count_stations()
    assert (counted["inspections"], counted["complete"]) == (2, False)
