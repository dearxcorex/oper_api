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
        "counts": {"BCS": 4},
        "stations": [
            station(1, 98.5, "BCS", "360101"),
            station(2, 91.0, "BCS2", "360101"),
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


def test_no_source_means_bcs(copy, gazetteer):
    assert ids(register.find(copy, gazetteer, province="ชัยภูมิ")) == [5, 3, 1]
    assert register.covers(copy, gazetteer, province="ชัยภูมิ")
    assert not register.covers(copy, gazetteer, province="ชัยภูมิ", source="BCS2")  # not walked


def test_places_match_by_pat_code_and_fall_back_to_the_address(copy, gazetteer):
    assert ids(register.find(copy, gazetteer, district="เกษตรสมบูรณ์")) == [3]
    assert ids(register.find(copy, gazetteer, province="ชัยภูมิ", district="เมืองชัยภูมิ",
                             subdistrict="ในเมือง")) == [5, 1]


def test_frequency_is_exact_and_name_is_a_substring(copy, gazetteer):
    assert ids(register.find(copy, gazetteer, frequency=92.25)) == [3]
    assert ids(register.find(copy, gazetteer, frequency=92.2)) == []
    assert ids(register.find(copy, gazetteer, name="รักสุข")) == [3]


def test_details_only_when_asked_and_never_coordinates_or_codes(copy, gazetteer):
    plain = register.find(copy, gazetteer, frequency=98.5)["stations"][0]
    full = register.find(copy, gazetteer, frequency=98.5, details=True)["stations"][0]
    assert "licence_no" not in plain and full["licence_no"] == "B1"
    for out in (plain, full):
        assert not {"lat", "lng", "pat_code", "raw"} & out.keys()


def test_limit_truncates(copy, gazetteer):
    result = register.find(copy, gazetteer, province="ชัยภูมิ", limit=1)
    assert (result["total"], result["shown"], result["truncated"]) == (3, 1, True)


class FakePortal:
    """station_search by source, and dSTN records; StnID 9 lives in every source."""

    def __init__(self, incomplete=None):
        self.incomplete = incomplete
        self.requests_sent = 0
        self.opened = []
        self.inspected = []
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

    # Inspections, newest first once sorted: station 9 has two (the newer one
    # with no phone), station 10 one whose form cannot be read.
    INSPECTIONS = [
        {"chk_id": 1, "station_code": "S9", "inspected_date": "2024-01-10"},
        {"chk_id": 2, "station_code": "S9", "inspected_date": "2026-03-01"},
        {"chk_id": 3, "station_code": "S9", "inspected_date": "2022-05-05"},
        {"chk_id": 4, "station_code": "S10", "inspected_date": "2026-02-01"},
    ]
    FORMS = {
        1: {"stn_id": 9, "contact_name": "สมชาย", "contact_phone": "081-111-1111", "inspected_date": "2024-01-10"},
        2: {"stn_id": 9, "contact_name": "สมชาย", "contact_phone": None, "inspected_date": "2026-03-01"},
        3: {"stn_id": 9, "contact_name": "เก่า", "contact_phone": "044-000000", "inspected_date": "2022-05-05"},
    }

    def search(self, *, province, **_):
        rows = self.INSPECTIONS if province == "36" else []
        return {"rows": rows, "total": len(rows), "complete": True}

    def inspection(self, chk_id, *, with_station=True, fresh=False):
        self.inspected.append(chk_id)
        if chk_id not in self.FORMS:
            raise NbtcError("no inspection form")
        return self.FORMS[chk_id]

    def _alternate_session(self):
        return "alternate"

    def station(self, stn_id, *, fresh=False, _session=None):
        self.opened.append(stn_id)
        if stn_id == 12:
            return {"pat_code": "100101", "licence_no": "L", "operator": "O"}
        if stn_id == 10 and _session != "alternate":
            raise NbtcError("empty")
        return {"pat_code": "360101", "licence_no": "L", "operator": "O", "lat": 15.0, "lng": 102.0}


def test_build_dedupes_across_sources_and_tries_the_other_login():
    copy = register.build(FakePortal(), sources=("WEB", "BCS", "BCS2"), log=lambda _: None)
    assert copy["counts"]["BCS"] == 4
    assert sorted(s["stn_id"] for s in copy["stations"]) == [9, 10]
    assert all(s["pat_code"] == "360101" and "lat" not in s for s in copy["stations"])


def test_build_takes_each_stations_phone_from_its_latest_inspection_that_has_one():
    portal = FakePortal()
    copy = register.build(portal, log=lambda _: None)
    contact = {s["stn_id"]: {k: s[k] for k in register.CONTACT_KEYS} for s in copy["stations"]}
    assert contact[9] == {"contact_name": "สมชาย", "contact_phone": "081-111-1111", "contact_date": "2024-01-10"}
    assert contact[10] == dict.fromkeys(register.CONTACT_KEYS)  # its only form was unreadable
    assert portal.inspected == [2, 4, 1]  # newest first; 3 skipped once 9 had a phone


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
