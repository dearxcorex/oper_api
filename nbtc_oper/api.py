"""The public surface: inspection search, inspection detail, station search and record."""

import json

from . import parse, places
from .client import NbtcError, Session
from .dates import to_portal_date

SEARCH_PATH = "/Oper/ISO/11/FF11ChkSch.aspx"
DETAIL_PATH = "/Oper/ISO/11/FF11Chk.aspx"
STATION_PATH = "/Oper/ISO/STN/dSTN.ashx"
STATION_SEARCH_PATH = "/Oper/ISO/STN/mStnSch.aspx"

# A result set that pages unstably is re-walked until every row is seen.
MAX_PASSES = 3


def build_query(
    *,
    inspected_from=None,
    inspected_to=None,
    recorded_from=None,
    recorded_to=None,
    reported_from=None,
    reported_to=None,
    province_id="0",
    district_id="0",
    subdistrict_id="0",
    station_name="",
    licence_no="",
    freq_from="",
    freq_to="",
    result="",
    source_type_id=0,
    unlicensed_only=False,
    warning_doc_no="",
    warning_doc_date=None,
    region_id=5,
    area_id=8,
    station_type_id=4,
    station_subtype_id=0,
) -> list[tuple[str, str]]:
    """Search filters -> the query string FF11ChkSch.aspx's own form produces."""
    return [
        ("StnSubTypeID_raw", "0"),
        ("RegID", str(region_id)),
        ("AreaID", str(area_id)),
        ("AreaID_raw", "0"),
        ("StaChk", "N" if unlicensed_only else ""),
        ("SrcTypeID", str(source_type_id)),
        ("StnTypeID", str(station_type_id)),
        ("StnSubTypeID", str(station_subtype_id)),
        ("sProv1", str(province_id)),
        ("sAumphoe1", str(district_id)),
        ("sTambol1", str(subdistrict_id)),
        ("OpinionDet", result or ""),
        ("StaNa", station_name or ""),
        ("StaNo", licence_no or ""),
        ("FreqMhz1", str(freq_from if freq_from is not None else "")),
        ("FreqMhz2", str(freq_to if freq_to is not None else "")),
        ("FDt", to_portal_date(inspected_from)),
        ("TDt", to_portal_date(inspected_to)),
        ("FDtA", to_portal_date(recorded_from)),
        ("TDtA", to_portal_date(recorded_to)),
        ("FDtR", to_portal_date(reported_from)),
        ("TDtR", to_portal_date(reported_to)),
        ("DocNFNo", warning_doc_no or ""),
        ("DtDocNF", to_portal_date(warning_doc_date)),
    ]


def build_station_query(
    *,
    name="",
    frequency="",
    location="",
    site_code="",
    licence_no="",
    source="",
    province_id="0",
    district_id="0",
    subdistrict_id="0",
    area_id=8,
    station_type_id=4,
    station_subtype_id=0,
) -> list[tuple[str, str]]:
    """Station filters -> the query string mStnSch.aspx's own form produces."""
    return [
        ("StnSubTypeID_raw", "0"),
        ("StnTypeID", str(station_type_id)),
        ("StnSubTypeID", str(station_subtype_id)),
        ("sProv1", str(province_id)),
        ("sAumphoe1", str(district_id)),
        ("sTambol1", str(subdistrict_id)),
        ("SrcData", source or ""),
        ("AreaID", str(area_id)),
        ("StnName", name or ""),
        ("Freq", str(frequency if frequency is not None else "")),
        ("StaLoc", location or ""),
        ("SiteCode", site_code or ""),
        ("LicNo", licence_no or ""),
        ("ff", "11"),
    ]


def station_key(row: dict):
    """What tells one station from another among inspection-search rows.

    The rows carry no StnID. The station code does the job when there is one;
    an unlicensed station has none and falls back to name, frequency, licence.
    """
    if row.get("station_code"):
        return row["station_code"]
    return (row.get("station_name"), row.get("frequency_mhz"), row.get("licence_no"))


class NbtcOper:
    def __init__(self, session: Session | None = None, **session_options):
        self.session = session or Session(**session_options)
        self._places = None
        self._alternate = None

    @property
    def requests_sent(self) -> int:
        return self.session.requests_sent + (self._alternate.requests_sent if self._alternate else 0)

    def _alternate_session(self) -> Session:
        """A second login under the portal's other VerID, with its own cookies and cache.

        The portal answers FF11Chk.aspx with an empty 200 when the inspection's
        station lives in the other version (legacy numeric codes sit under VerID 1).
        """
        if self._alternate is None:
            main = self.session
            ver_id = "1" if main.ver_id != "1" else "2"
            username, password = main._credentials or (None, None)
            self._alternate = Session(
                username,
                password,
                ver_id=ver_id,
                min_interval=main.min_interval,
                cache_ttl=main.cache_ttl,
                state_dir=main.state_dir / f"ver{ver_id}",
                timeout=main.timeout,
            )
        return self._alternate

    def places(self) -> dict:
        """The portal's province/district/sub-district code tables."""
        if self._places is None:
            path = self.session.state_dir / "places.json"
            if path.is_file():
                self._places = json.loads(path.read_text(encoding="utf-8"))
            else:
                self._places = places.parse_dpv(self.session.get(places.DPV_PATH))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(self._places, ensure_ascii=False), encoding="utf-8")
        return self._places

    def search(
        self,
        *,
        province=None,
        district=None,
        subdistrict=None,
        max_pages: int | None = None,
        fresh: bool = False,
        **filters,
    ) -> dict:
        """Every inspection matching the filters, all pages, deduped on chk_id.

        Dates are ISO ('2026-01-01'); places are Thai names or portal codes.
        See build_query() for the full filter list.
        """
        if province or district or subdistrict:
            prov, dist, sub = places.resolve(self.places(), province, district, subdistrict)
            filters.update(province_id=prov, district_id=dist, subdistrict_id=sub)
        return self._walk(
            SEARCH_PATH, build_query(**filters), parse.parse_search_page, "chk_id", max_pages, fresh
        )

    def count_stations(self, *, fresh: bool = False, **filters) -> dict:
        """Distinct stations among the matching inspections. Walks every page."""
        result = self.search(fresh=fresh, **filters)
        return {
            "inspections": result["total"],
            "stations": len({station_key(row) for row in result["rows"]}),
            "complete": result["complete"],
        }

    def station_search(
        self,
        *,
        province=None,
        district=None,
        subdistrict=None,
        max_pages: int | None = None,
        fresh: bool = False,
        **filters,
    ) -> dict:
        """Every register station matching the filters, all pages, deduped on stn_id.

        This is the picker behind the inspection form's station field; unlike
        search() it also lists stations nobody has inspected. `source` is the
        portal's SrcData (ASMS, WEB, BCS, BCS2, BCS3, OPER). See
        build_station_query() for the full filter list.
        """
        if province or district or subdistrict:
            prov, dist, sub = places.resolve(self.places(), province, district, subdistrict)
            filters.update(province_id=prov, district_id=dist, subdistrict_id=sub)
        return self._station_walk(filters, max_pages, fresh)

    def _station_walk(self, filters, max_pages, fresh) -> dict:
        """Walk the picker; if paging loses rows, re-ask one place level down.

        The picker orders its pages unstably, so a station can repeat on several
        pages while another never shows. A slice small enough for one page has
        no such gap, so an incomplete result is filled in province by province,
        then district by district, then sub-district by sub-district.
        """
        query = build_station_query(**filters)
        result = self._walk(
            STATION_SEARCH_PATH, query, parse.parse_station_search_page, "stn_id", max_pages, fresh
        )
        if result["complete"] or max_pages is not None or result["total"] is None:
            return result
        rows = {row["stn_id"]: row for row in result["rows"]}
        for narrower in self._narrower(filters, query):
            if len(rows) >= result["total"]:
                break
            for row in self._station_walk({**filters, **narrower}, None, fresh)["rows"]:
                rows.setdefault(row["stn_id"], row)
        result["rows"] = list(rows.values())
        result["complete"] = len(rows) >= result["total"]
        return result

    def _narrower(self, filters, query) -> list[dict]:
        province, district, subdistrict = (
            str(filters.get(k, "0")) for k in ("province_id", "district_id", "subdistrict_id")
        )
        if subdistrict != "0":
            return []
        if district != "0":
            return [{"subdistrict_id": c} for c in self.places()["subdistricts"].get(district, {})]
        if province != "0":
            return [{"district_id": c} for c in self.places()["districts"].get(province, {})]
        first_page = self.session.get(STATION_SEARCH_PATH, query + [("page", "1")])
        return [{"province_id": c} for c in parse.station_search_provinces(first_page)]

    def _walk(self, path, query, parse_page, key, max_pages, fresh) -> dict:
        rows, total, pages = {}, None, 1
        for attempt in range(MAX_PASSES):
            page = 1
            while page <= pages and (max_pages is None or page <= max_pages):
                html = self.session.get(
                    path, query + [("page", str(page))], fresh=fresh or attempt > 0
                )
                parsed = parse_page(html)
                if page == 1:
                    total, pages = parsed["total"], parsed["pages"]
                for row in parsed["rows"]:
                    rows.setdefault(row[key], row)
                page += 1
            if max_pages is not None or total is None or len(rows) >= total:
                break

        return {
            "query": dict(query),
            "total": total,
            "pages": pages,
            "complete": total is not None and len(rows) >= total,
            "rows": list(rows.values()),
        }

    def station(self, stn_id: int, *, fresh: bool = False, _session: Session | None = None) -> dict:
        """The register record behind a StnID, coordinates included."""
        session = _session or self.session
        text = session.post(STATION_PATH, {"StnID": str(stn_id)}, fresh=fresh)
        try:
            records = json.loads(text)
        except json.JSONDecodeError as exc:
            raise NbtcError(f"dSTN.ashx returned no JSON for StnID {stn_id}") from exc
        if not records:
            raise NbtcError(f"no station with StnID {stn_id}")
        return parse.shape_station(records[0])

    def inspection(self, chk_id: int, *, with_station: bool = True, fresh: bool = False) -> dict:
        """One inspection record; lat/lng and station codes come from its station."""
        session = self.session
        html = session.get(DETAIL_PATH, [("ChkID", str(chk_id))], fresh=fresh)
        if not html.strip():
            session = self._alternate_session()
            html = session.get(DETAIL_PATH, [("ChkID", str(chk_id))], fresh=fresh)
        detail = parse.parse_detail_page(html, int(chk_id))
        if not detail["raw"]:
            raise NbtcError(f"no inspection form found for ChkID {chk_id}")
        detail["ver_id"] = session.ver_id
        station = None
        if with_station and detail["stn_id"]:
            station = self.station(detail["stn_id"], fresh=fresh, _session=session)
        detail["lat"] = station["lat"] if station else None
        detail["lng"] = station["lng"] if station else None
        detail["station_id"] = station["station_id"] if station else None
        detail["nbtc_code"] = station["nbtc_code"] if station else None
        detail["station"] = station
        return detail
