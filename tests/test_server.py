import os
import threading
import time

import pytest
from fastapi.testclient import TestClient

from nbtc_oper import CloudflareChallenge, NbtcError, places, register
from nbtc_oper.places import UnknownPlace
from server.app import DETAILS_LIMIT, LIVE_TIME_LIMIT, create_app

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeApi:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def places(self):
        return places.parse_dpv(open("tests/fixtures/dpv_sample.js", encoding="utf-8").read())

    def find_stations(self, **kwargs):
        self.calls.append(("find_stations", kwargs))
        if self.error:
            raise self.error
        return {"total": 1, "shown": 1, "truncated": False, "complete": True, "stations": []}

    def count_stations(self, **kwargs):
        self.calls.append(("count_stations", kwargs))
        if self.error:
            raise self.error
        return {"inspections": 126, "stations": 122, "by_result": {}, "complete": True}

    def content_inspections(self, **kwargs):
        self.calls.append(("content_inspections", kwargs))
        return {"work": "งานคุ้มครอง", "inspections": 3, "stations": 3, "station_list": []}


@pytest.fixture
def register_file(tmp_path):
    return tmp_path / "register.json"


@pytest.fixture
def make_client(monkeypatch, register_file):
    monkeypatch.setenv("OPER_API_TOKEN", TOKEN)

    def make(api):
        return TestClient(create_app(lambda: api, register_file=register_file))

    return make


def test_health_needs_no_token_and_no_portal(make_client):
    api = FakeApi()
    assert make_client(api).get("/health").json() == {"ok": True, "as_of": None, "refreshing": False}
    assert api.calls == []


def test_health_reports_the_copys_as_of(make_client, register_file):
    register.save(saved_copy((1, 98.5, "BCS")), register_file)
    assert make_client(FakeApi()).get("/health").json()["as_of"] == "2026-10-16T03:00:00+00:00"


def test_wrong_or_missing_token_is_rejected(make_client):
    client = make_client(FakeApi())
    assert client.post("/find-stations", json={"frequency": 98.5}).status_code == 401
    assert client.post("/find-stations", json={"frequency": 98.5},
                       headers={"Authorization": "Bearer nope"}).status_code == 401


def test_unset_token_refuses_everything(monkeypatch, register_file):
    monkeypatch.delenv("OPER_API_TOKEN", raising=False)
    client = TestClient(create_app(FakeApi, register_file=register_file))
    assert client.post("/find-stations", json={"frequency": 98.5}, headers=AUTH).status_code == 500


def test_find_stations_passes_filters_through(make_client):
    api = FakeApi()
    res = make_client(api).post("/find-stations", headers=AUTH, json={
        "province": "นครราชสีมา", "district": "เมืองนครราชสีมา", "frequency": 98.5, "source": "BCS",
    })
    assert res.status_code == 200
    assert api.calls == [("find_stations", {
        "province": "นครราชสีมา", "district": "เมืองนครราชสีมา", "frequency": 98.5,
        "source": "BCS", "limit": 25, "details": False, "time_limit": LIVE_TIME_LIMIT,
    })]


def test_details_caps_the_limit(make_client):
    api = FakeApi()
    make_client(api).post("/find-stations", headers=AUTH, json={"frequency": 98.5, "details": True, "limit": 50})
    assert api.calls[0][1]["limit"] == DETAILS_LIMIT


def saved_copy(*stations):
    return {"built_at": "2026-10-16T03:00:00+00:00", "counts": {"BCS": len(stations), "OPER": 0}, "stations": [
        {"stn_id": i, "name": f"สถานี {i}", "frequency_mhz": f, "source": src, "pat_code": "360101",
         "licence_no": "L", "lat": 15.0}
        for i, f, src in stations
    ]}


def test_find_stations_answers_from_the_saved_register(make_client, register_file):
    register.save(saved_copy((1, 98.5, "BCS"), (2, 91.0, "BCS2")), register_file)
    api = FakeApi()
    res = make_client(api).post("/find-stations", headers=AUTH, json={"province": "ชัยภูมิ", "source": "BCS"})
    body = res.json()
    assert [s["stn_id"] for s in body["stations"]] == [1]
    assert body["as_of"] == "2026-10-16T03:00:00+00:00"
    assert api.calls == []  # no portal walk


def test_a_province_outside_the_saved_register_is_walked_live(make_client, register_file):
    copy = saved_copy((1, 98.5, "BCS"))
    copy["provinces"] = ["36"]
    register.save(copy, register_file)
    api = FakeApi()
    res = make_client(api).post("/find-stations", headers=AUTH, json={"province": "นครราชสีมา"})
    assert "as_of" not in res.json()
    assert api.calls[0][1]["time_limit"] == LIVE_TIME_LIMIT


def test_details_from_the_saved_register_are_not_capped(make_client, register_file):
    register.save(saved_copy(*[(i, 88.0 + i, "BCS") for i in range(1, 16)]), register_file)
    res = make_client(FakeApi()).post("/find-stations", headers=AUTH,
                                      json={"province": "ชัยภูมิ", "details": True, "limit": 15})
    assert res.json()["shown"] == 15


def test_a_rebuilt_register_is_picked_up(make_client, register_file):
    client = make_client(FakeApi())
    register.save(saved_copy((1, 98.5, "BCS")), register_file)
    assert client.post("/find-stations", headers=AUTH, json={"province": "ชัยภูมิ"}).json()["total"] == 1
    copy = saved_copy((1, 98.5, "BCS"), (2, 99.0, "BCS"))
    copy["built_at"] = "2026-10-17T03:00:00+00:00"
    register.save(copy, register_file)
    os.utime(register_file, (1e9, 2e9))  # a new mtime even within the same clock tick
    assert client.post("/find-stations", headers=AUTH, json={"province": "ชัยภูมิ"}).json()["total"] == 2


def test_unknown_fields_and_sources_are_rejected(make_client):
    client = make_client(FakeApi())
    assert client.post("/find-stations", headers=AUTH, json={"lat": 15.0}).status_code == 422
    assert client.post("/find-stations", headers=AUTH, json={"source": "XYZ"}).status_code == 422


def test_count_stations_echoes_the_date_range(make_client):
    api = FakeApi()
    res = make_client(api).post("/count-stations", headers=AUTH, json={
        "inspected_from": "2026-01-01", "inspected_to": "2026-10-15", "province": "ชัยภูมิ",
    })
    assert res.json() == {
        "inspections": 126, "stations": 122, "by_result": {}, "complete": True,
        "inspected_from": "2026-01-01", "inspected_to": "2026-10-15",
    }
    assert api.calls == [("count_stations", {
        "inspected_from": "2026-01-01", "inspected_to": "2026-10-15",
        "province": "ชัยภูมิ", "district": None, "result": None, "limit": 25,
    })]


def test_count_stations_passes_the_result_filter(make_client):
    api = FakeApi()
    res = make_client(api).post("/count-stations", headers=AUTH, json={
        "inspected_from": "2026-01-01", "inspected_to": "2026-10-16", "result": "ตรงตามมาตรฐาน",
    })
    assert res.status_code == 200
    assert api.calls[0][1]["result"] == "ตรงตามมาตรฐาน"


def test_count_stations_rejects_an_unknown_result(make_client):
    res = make_client(FakeApi()).post("/count-stations", headers=AUTH, json={
        "inspected_from": "2026-01-01", "inspected_to": "2026-10-16", "result": "ผ่าน",
    })
    assert res.status_code == 422


def test_count_stations_rejects_a_backwards_range(make_client):
    res = make_client(FakeApi()).post("/count-stations", headers=AUTH, json={
        "inspected_from": "2026-10-15", "inspected_to": "2026-01-01",
    })
    assert res.status_code == 400


def test_content_inspections_passes_only_the_given_filters(make_client):
    api = FakeApi()
    res = make_client(api).post("/content-inspections", headers=AUTH, json={
        "frequency": 88, "result": "พบการกระทำผิด",
    })
    assert res.status_code == 200
    assert res.json()["work"] == "งานคุ้มครอง"
    assert api.calls == [("content_inspections", {"frequency": 88.0, "result": "พบการกระทำผิด", "limit": 25})]


def test_content_inspections_passes_dates_through(make_client):
    from datetime import date

    api = FakeApi()
    make_client(api).post("/content-inspections", headers=AUTH, json={
        "inspected_from": "2026-01-01", "inspected_to": "2026-10-16",
    })
    assert api.calls[0][1] == {"inspected_from": date(2026, 1, 1), "inspected_to": date(2026, 10, 16), "limit": 25}


@pytest.mark.parametrize("body, status", [
    ({"result": "ผิด"}, 422),
    ({"source_type": "อื่นๆ"}, 422),
    ({"inspected_from": "2026-10-15", "inspected_to": "2026-01-01"}, 400),
    ({"frequency": 88, "colour": "red"}, 422),
])
def test_content_inspections_rejects_bad_input(make_client, body, status):
    assert make_client(FakeApi()).post("/content-inspections", headers=AUTH, json=body).status_code == status


@pytest.mark.parametrize("error, status, kind", [
    (CloudflareChallenge("challenged"), 503, "cloudflare"),
    (UnknownPlace("district 'x' not found"), 400, "unknown_place"),
])
def test_portal_errors_map_to_status_codes(make_client, error, status, kind):
    res = make_client(FakeApi(error)).post("/find-stations", headers=AUTH, json={"district": "x"})
    assert res.status_code == status
    assert res.json()["error"] == kind


# ---------- /refresh ----------

def wait_until_idle(client):
    for _ in range(200):
        if not client.get("/health").json()["refreshing"]:
            return
        time.sleep(0.01)
    raise AssertionError("refresh still running")


def test_refresh_needs_the_token(make_client):
    assert make_client(FakeApi()).post("/refresh").status_code == 401


def test_refresh_rebuilds_in_the_background(make_client, register_file, monkeypatch):
    monkeypatch.setattr(register, "build", lambda api, **_: saved_copy((1, 98.5, "BCS")))
    client = make_client(FakeApi())
    assert client.post("/refresh", headers=AUTH).status_code == 202
    wait_until_idle(client)
    assert client.get("/health").json()["as_of"] == "2026-10-16T03:00:00+00:00"


def test_a_second_refresh_is_refused_while_one_runs(make_client, register_file, monkeypatch):
    release = threading.Event()

    def slow_build(api, **_):
        release.wait(5)
        return saved_copy((1, 98.5, "BCS"))

    monkeypatch.setattr(register, "build", slow_build)
    client = make_client(FakeApi())
    assert client.post("/refresh", headers=AUTH).status_code == 202
    second = client.post("/refresh", headers=AUTH)
    assert (second.status_code, second.json()["error"]) == (409, "busy")
    # questions still answer while it runs
    assert client.post("/count-stations", headers=AUTH, json={
        "inspected_from": "2026-01-01", "inspected_to": "2026-10-16"}).status_code == 200
    release.set()
    wait_until_idle(client)
    assert client.post("/refresh", headers=AUTH).status_code == 202
    wait_until_idle(client)


def test_a_failed_refresh_keeps_the_last_good_copy(make_client, register_file, monkeypatch):
    register.save(saved_copy((1, 98.5, "BCS")), register_file)

    def failing_build(api, **_):
        raise NbtcError("source BCS2: 200 of 243 stations seen")

    monkeypatch.setattr(register, "build", failing_build)
    client = make_client(FakeApi())
    assert client.post("/refresh", headers=AUTH).status_code == 202
    wait_until_idle(client)
    assert client.get("/health").json()["as_of"] == "2026-10-16T03:00:00+00:00"
    assert client.post("/find-stations", headers=AUTH, json={"province": "ชัยภูมิ"}).json()["total"] == 1
