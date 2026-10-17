"""skills/oper-api/operClient.ts must match what the server takes and returns."""

import re
import typing
from pathlib import Path

from fastapi.testclient import TestClient

from nbtc_oper import NbtcOper, places, register
from server.app import ContentInspections, CountStations, FindStations, create_app

CLIENT = (Path(__file__).parent.parent / "skills/oper-api/operClient.ts").read_text(encoding="utf-8")
GAZETTEER = places.parse_dpv((Path(__file__).parent / "fixtures/dpv_sample.js").read_text(encoding="utf-8"))


def interface(name: str) -> set[str]:
    body = re.search(r"export interface " + name + r" \{(.*?)\n\}", CLIENT, re.S)
    assert body, f"interface {name} not found in operClient.ts"
    return set(re.findall(r"^\s*(\w+)\??:", body.group(1), re.M))


def const_list(name: str) -> list[str]:
    body = re.search(r"export const " + name + r" = \[(.*?)\] as const", CLIENT, re.S)
    assert body, f"{name} not found in operClient.ts"
    return re.findall(r"'([^']*)'", body.group(1))


def literal(model, field: str) -> list[str]:
    choices = next(a for a in typing.get_args(model.model_fields[field].annotation) if a is not type(None))
    return list(typing.get_args(choices))


def test_requests_match_the_server_models():
    assert interface("FindStationsRequest") == set(FindStations.model_fields)
    assert interface("CountStationsRequest") == set(CountStations.model_fields)
    assert const_list("OPER_SOURCES") == literal(FindStations, "source")
    assert const_list("OPER_RESULTS") == literal(CountStations, "result")


def test_station_summary_has_every_key_the_server_returns():
    row = {"stn_id": 1, "name": "สถานี", "frequency_mhz": 98.5, "source": "BCS",
           "location": "1 ต.ในเมือง อ.เมืองชัยภูมิ จ.ชัยภูมิ"}
    entry = register._entry(row, {"pat_code": "360101", "lat": 15.8, "lng": 102.0})
    entry.update(dict.fromkeys(register.CONTACT_KEYS))
    copy = {"built_at": "2026-10-16T03:00:00+00:00", "counts": {"BCS": 1},
            "provinces": ["36"], "stations": [entry]}
    result = register.find(copy, GAZETTEER, details=True)
    assert interface("FindStationsResponse") == set(result) | {"provinces", "as_of"}
    assert interface("StationSummary") == set(result["stations"][0])


def test_count_and_health_responses_match():
    class Portal:
        def search(self, **_):
            rows = [{"chk_id": 1, "station_code": "S1", "result": "ตรงตามมาตรฐาน"}]
            return {"rows": rows, "total": 1, "complete": True}

    counted = NbtcOper.count_stations(Portal())
    assert interface("CountStationsResponse") == set(counted) | {"inspected_from", "inspected_to"}
    assert interface("ResultCount") == set(next(iter(counted["by_result"].values())))
    health = TestClient(create_app(make_api=lambda: None)).get("/health").json()
    assert interface("HealthResponse") == set(health)


def test_content_inspections_match():
    assert interface("ContentInspectionsRequest") == set(ContentInspections.model_fields)
    assert const_list("CONTENT_RESULTS") == literal(ContentInspections, "result")
    assert const_list("CONTENT_SOURCE_TYPES") == literal(ContentInspections, "source_type")

    class Portal:
        def content_search(self, **_):
            rows = [{"chk_id": 1, "station_code": "S1", "inspected_date": "2026-03-10",
                     "result": "ไม่พบการกระทำผิด"}]
            return {"rows": rows, "total": 1, "complete": True}

    found = NbtcOper.content_inspections(Portal(), inspected_from="2026-01-01")
    assert interface("ContentInspectionsResponse") == set(found)
    station = found["station_list"][0]
    assert interface("ContentStation") == set(station)
    assert interface("ContentCheck") == set(station["checks"][0])
    assert "/content-inspections" in CLIENT
