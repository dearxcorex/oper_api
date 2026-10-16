import pytest
from fastapi.testclient import TestClient

from nbtc_oper import CloudflareChallenge
from nbtc_oper.places import UnknownPlace
from server.app import DETAILS_LIMIT, create_app

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeApi:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

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


@pytest.fixture
def make_client(monkeypatch):
    monkeypatch.setenv("OPER_API_TOKEN", TOKEN)

    def make(api):
        return TestClient(create_app(lambda: api))

    return make


def test_health_needs_no_token_and_no_portal(make_client):
    api = FakeApi()
    assert make_client(api).get("/health").json() == {"ok": True}
    assert api.calls == []


def test_wrong_or_missing_token_is_rejected(make_client):
    client = make_client(FakeApi())
    assert client.post("/find-stations", json={"frequency": 98.5}).status_code == 401
    assert client.post("/find-stations", json={"frequency": 98.5},
                       headers={"Authorization": "Bearer nope"}).status_code == 401


def test_unset_token_refuses_everything(monkeypatch):
    monkeypatch.delenv("OPER_API_TOKEN", raising=False)
    client = TestClient(create_app(FakeApi))
    assert client.post("/find-stations", json={"frequency": 98.5}, headers=AUTH).status_code == 500


def test_find_stations_passes_filters_through(make_client):
    api = FakeApi()
    res = make_client(api).post("/find-stations", headers=AUTH, json={
        "province": "นครราชสีมา", "district": "เมืองนครราชสีมา", "frequency": 98.5, "source": "BCS",
    })
    assert res.status_code == 200
    assert api.calls == [("find_stations", {
        "province": "นครราชสีมา", "district": "เมืองนครราชสีมา", "frequency": 98.5,
        "source": "BCS", "limit": 25, "details": False,
    })]


def test_details_caps_the_limit(make_client):
    api = FakeApi()
    make_client(api).post("/find-stations", headers=AUTH, json={"frequency": 98.5, "details": True, "limit": 50})
    assert api.calls[0][1]["limit"] == DETAILS_LIMIT


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
        "province": "ชัยภูมิ", "district": None, "result": None,
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


@pytest.mark.parametrize("error, status, kind", [
    (CloudflareChallenge("challenged"), 503, "cloudflare"),
    (UnknownPlace("district 'x' not found"), 400, "unknown_place"),
])
def test_portal_errors_map_to_status_codes(make_client, error, status, kind):
    res = make_client(FakeApi(error)).post("/find-stations", headers=AUTH, json={"district": "x"})
    assert res.status_code == status
    assert res.json()["error"] == kind
