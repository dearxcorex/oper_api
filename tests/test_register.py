from pathlib import Path

import pytest

from nbtc_oper import NbtcError, parse, places, register

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def gazetteer():
    return places.parse_dpv((FIXTURES / "dpv_sample.js").read_text(encoding="utf-8"))


def station(stn_id, freq, source, pat_code, name="สถานี", location=None, licence="B1"):
    return {
        "stn_id": stn_id, "name": f"{name} {stn_id}", "frequency_mhz": freq,
        "station_code": None, "station_subtype": None, "source": source,
        **parse.split_location(location), "location": location,
        "licence_no": licence, "licence_expires": None, "operator": "ผู้ประกอบการ",
        "nbtc_code": None, "station_id": None, "pat_code": pat_code,
    }


@pytest.fixture
def copy():
    return {
        "built_at": "2026-10-16T03:00:00+00:00",
        "counts": {"BCS": 4, "OPER": 1},
        "stations": [
            station(1, 98.5, "BCS", "360101"),
            station(2, 91.0, "BCS2", "360101"),
            station(6, 88.0, "OPER", "360101"),
            station(3, 92.25, "BCS", "360403", name="คนรักสุขภาพ"),
            station(4, 0.0, "BCS", "360101"),
            station(5, 89.0, "BCS", None, location="1 ต.ในเมือง อ.เมืองชัยภูมิ จ.ชัยภูมิ"),
        ],
    }


def ids(result):
    return [s["stn_id"] for s in result["stations"]]


def test_source_matches_exactly(copy, gazetteer):
    result = register.find(copy, gazetteer, province="ชัยภูมิ", source="BCS")
    assert ids(result) == [5, 3, 1]  # not BCS2, not 0.0 MHz; by frequency
    assert (result["total"], result["complete"], result["as_of"]) == (3, True, copy["built_at"])
    assert ids(register.find(copy, gazetteer, province="ชัยภูมิ", source="BCS2")) == [2]


def test_no_source_means_bcs_and_oper(copy, gazetteer):
    assert ids(register.find(copy, gazetteer, province="ชัยภูมิ")) == [6, 5, 3, 1]
    assert register.covers(copy, gazetteer, province="ชัยภูมิ")
    assert not register.covers(copy, gazetteer, province="ชัยภูมิ", source="BCS2")  # not walked
    del copy["counts"]["OPER"]  # a copy built before OPER was walked
    assert not register.covers(copy, gazetteer, province="ชัยภูมิ")
    assert register.covers(copy, gazetteer, province="ชัยภูมิ", source="BCS")


def test_a_station_listed_under_both_sources_matches_either(copy, gazetteer):
    copy["stations"][0]["sources"] = ["BCS", "OPER"]
    assert ids(register.find(copy, gazetteer, province="ชัยภูมิ", source="OPER")) == [6, 1]
    assert "sources" not in register.find(copy, gazetteer, frequency=98.5)["stations"][0]


def test_places_match_by_pat_code_and_fall_back_to_the_address(copy, gazetteer):
    assert ids(register.find(copy, gazetteer, district="เกษตรสมบูรณ์")) == [3]
    assert ids(register.find(copy, gazetteer, province="ชัยภูมิ", district="เมืองชัยภูมิ",
                             subdistrict="ในเมือง")) == [6, 5, 1]


def test_frequency_is_exact_and_name_is_a_substring(copy, gazetteer):
    assert ids(register.find(copy, gazetteer, frequency=92.25)) == [3]
    assert ids(register.find(copy, gazetteer, frequency=92.2)) == []
    assert ids(register.find(copy, gazetteer, name="รักสุข")) == [3]


def test_details_only_when_asked_coordinates_always_and_never_codes(copy, gazetteer):
    copy["stations"][0].update(lat=15.8, lng=102.0)
    plain = register.find(copy, gazetteer, frequency=98.5)["stations"][0]
    full = register.find(copy, gazetteer, frequency=98.5, details=True)["stations"][0]
    assert "licence_no" not in plain and full["licence_no"] == "B1"
    for out in (plain, full):
        assert (out["lat"], out["lng"]) == (15.8, 102.0)
        assert not {"pat_code", "raw"} & out.keys()


def test_limit_truncates(copy, gazetteer):
    result = register.find(copy, gazetteer, province="ชัยภูมิ", limit=1)
    assert (result["total"], result["shown"], result["truncated"]) == (4, 1, True)


class FakePortal:
    """station_search by source, and dSTN records; StnID 9 lives in every source."""

    def __init__(self, incomplete=None):
        self.incomplete = incomplete
        self.requests_sent = 0
        self.opened = []
        self.session = object()

    def places(self):
        return places.parse_dpv((FIXTURES / "dpv_sample.js").read_text(encoding="utf-8"))

    def station_search(self, *, source, **_):
        rows = [{"stn_id": 9, "name": "ซ้ำ", "frequency_mhz": 90.0, "source": source, "location": None}]
        if source == "BCS":
            rows += [
                {"stn_id": 10, "name": "บี", "frequency_mhz": 95.0, "source": "BCS", "location": None},
                {"stn_id": 11, "name": "กรุง", "frequency_mhz": 96.0, "source": "BCS",
                 "location": "1 แขวงคลองเตย เขตคลองเตย จ.กรุงเทพมหานคร"},
                {"stn_id": 12, "name": "นอกเขต", "frequency_mhz": 97.0, "source": "BCS", "location": None},
            ]
        return {"rows": rows, "total": len(rows) + (source == self.incomplete),
                "complete": source != self.incomplete}

    def _alternate_session(self):
        return "alternate"

    def station(self, stn_id, *, fresh=False, _session=None):
        self.opened.append(stn_id)
        if stn_id == 12:
            return {"pat_code": "100101", "licence_no": "L", "operator": "O"}
        if stn_id == 10 and _session != "alternate":
            raise NbtcError("empty")
        record = {"pat_code": "360101", "licence_no": "L", "operator": "O", "lat": 15.0, "lng": 102.0,
                  "contact_name": None, "contact_phone": None, "updated_at": "2025-06-01"}
        if stn_id == 9:
            record.update(contact_name="สมชาย", contact_phone="081-111-1111")
        return record


def test_build_dedupes_across_sources_and_tries_the_other_login():
    copy = register.build(FakePortal(), sources=("WEB", "BCS", "BCS2"), log=lambda _: None)
    assert copy["counts"]["BCS"] == 4
    assert sorted(s["stn_id"] for s in copy["stations"]) == [9, 10]
    assert all(s["pat_code"] == "360101" for s in copy["stations"])
    assert all((s["lat"], s["lng"]) == (15.0, 102.0) for s in copy["stations"])
    assert {s["stn_id"]: s["sources"] for s in copy["stations"]}[9] == ["WEB", "BCS", "BCS2"]


def test_build_takes_each_stations_phone_from_its_record():
    copy = register.build(FakePortal(), log=lambda _: None)
    contact = {s["stn_id"]: {k: s[k] for k in register.CONTACT_KEYS} for s in copy["stations"]}
    assert contact[9] == {"contact_name": "สมชาย", "contact_phone": "081-111-1111", "contact_date": "2025-06-01"}
    assert contact[10] == dict.fromkeys(register.CONTACT_KEYS)  # its record has no phone


def test_shape_station_keeps_the_coordinators_name_and_phone():
    shaped = parse.shape_station({"StnID": 1, "CoopNa": " สมชาย ", "CoopTel": "081-111-1111"})
    assert (shaped["contact_name"], shaped["contact_phone"]) == ("สมชาย", "081-111-1111")
    blank = parse.shape_station({"StnID": 2, "CoopNa": "-", "CoopTel": ""})
    assert (blank["contact_name"], blank["contact_phone"]) == (None, None)


def test_contacts_show_without_details(copy, gazetteer):
    copy["stations"][0].update(contact_name="สมชาย", contact_phone="081-111-1111")
    plain = register.find(copy, gazetteer, frequency=98.5)["stations"][0]
    assert plain["contact_phone"] == "081-111-1111" and "licence_no" not in plain


def test_build_keeps_only_the_offices_provinces():
    portal = FakePortal()
    copy = register.build(portal, log=lambda _: None)
    assert copy["provinces"] == ["30", "36"]
    assert sorted(s["stn_id"] for s in copy["stations"]) == [9, 10]  # 12's PATCode is Bangkok
    assert 11 not in portal.opened  # its address already says Bangkok


def test_the_copy_covers_only_its_provinces(copy, gazetteer):
    copy["provinces"] = ["36"]
    assert register.covers(copy, gazetteer, province="ชัยภูมิ")
    assert register.covers(copy, gazetteer, district="เมืองชัยภูมิ")
    assert register.covers(copy, gazetteer, frequency=98.5)  # no place: the copy's provinces
    assert not register.covers(copy, gazetteer, province="นครราชสีมา")
    assert register.find(copy, gazetteer, frequency=98.5)["provinces"] == ["ชัยภูมิ"]
    assert "provinces" not in register.find(copy, gazetteer, province="ชัยภูมิ")
    del copy["provinces"]
    assert register.covers(copy, gazetteer, province="นครราชสีมา")  # an older, whole-area copy


def test_build_refuses_an_incomplete_source():
    with pytest.raises(NbtcError, match="BCS2"):
        register.build(FakePortal(incomplete="BCS2"), sources=("BCS", "BCS2"), log=lambda _: None)


def test_save_and_load_round_trip(tmp_path, copy):
    path = tmp_path / "register.json"
    assert register.load(path) is None
    register.save(copy, path)
    assert register.load(path) == copy
    assert not list(tmp_path.glob("*.tmp"))


def test_rebuild_keeps_the_last_good_copy_when_the_build_fails(tmp_path, copy):
    path = tmp_path / "register.json"
    register.save(copy, path)
    with pytest.raises(NbtcError):
        register.rebuild(FakePortal(incomplete="BCS"), path, log=lambda _: None)
    assert register.load(path) == copy
    register.rebuild(FakePortal(), path, log=lambda _: None)  # the lock was let go
    assert register.load(path)["counts"]["BCS"] == 4


def test_only_one_rebuild_at_a_time(tmp_path):
    path = tmp_path / "register.json"
    held = register.BuildLock(path)
    held.acquire()
    with pytest.raises(register.Busy):
        register.rebuild(FakePortal(), path, log=lambda _: None)
    held.release()
    assert not path.exists()
