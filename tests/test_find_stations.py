"""find_stations walking the portal live, against a fake slow session."""
from pathlib import Path

from nbtc_oper import NbtcOper, places

FIXTURES = Path(__file__).parent / "fixtures"
PAGE = (FIXTURES / "station_search_page.html").read_text(encoding="utf-8")  # 20 of 282


class SlowSession:
    """Every page takes 10 s on a fake clock and shows the same 20 stations,
    so the walk never completes on its own."""

    def __init__(self, tmp_path):
        self.now = 0.0
        self.requests_sent = 0
        self.state_dir = tmp_path

    def clock(self):
        return self.now

    def get(self, path, params=None, *, fresh=False):
        self.now += 10
        self.requests_sent += 1
        return PAGE


def api_for(session):
    api = NbtcOper(session=session)
    api.clock = session.clock
    api._places = places.parse_dpv((FIXTURES / "dpv_sample.js").read_text(encoding="utf-8"))
    return api


def test_a_live_walk_stops_at_the_time_limit(tmp_path):
    session = SlowSession(tmp_path)
    result = api_for(session).find_stations(province="ชัยภูมิ", time_limit=40)
    assert session.now <= 40
    assert result["complete"] is False
    assert result["total"] == 282  # the portal's own count
    assert result["shown"] == 20 and result["truncated"]


def test_details_past_the_limit_come_back_without_a_record(tmp_path):
    session = SlowSession(tmp_path)
    result = api_for(session).find_stations(province="ชัยภูมิ", details=True, time_limit=5)
    assert session.requests_sent == 1  # page 1, then no station records
    assert result["complete"] is False and "licence_no" not in result["stations"][0]


class RecordingSession(SlowSession):
    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.provinces = []

    def get(self, path, params=None, *, fresh=False):
        self.provinces.append(dict(params)["sProv1"])
        return super().get(path, params, fresh=fresh)


def test_a_search_with_no_place_walks_only_the_offices_provinces(tmp_path):
    session = RecordingSession(tmp_path)
    result = api_for(session).find_stations(frequency=91.75, time_limit=15)
    assert session.provinces == ["30", "36"]  # one page each before the limit
    assert result["provinces"] == ["นครราชสีมา", "ชัยภูมิ"]
    assert result["complete"] is False


def test_a_named_place_is_walked_alone(tmp_path):
    session = RecordingSession(tmp_path)
    result = api_for(session).find_stations(province="ชัยภูมิ", time_limit=5)
    assert session.provinces == ["36"] and "provinces" not in result


def test_a_district_in_several_provinces_goes_to_the_offices():
    gazetteer = {
        "provinces": {"10": "กรุงเทพมหานคร", "30": "จ.นครราชสีมา", "40": "จ.ขอนแก่น"},
        "districts": {"30": {"3001": "อ.บ้านเหลื่อม"}, "40": {"4001": "อ.บ้านเหลื่อม"}},
        "subdistricts": {},
    }
    assert places.resolve_loose(gazetteer, district="บ้านเหลื่อม") == ("30", "3001", "0")
