"""The public surface: inspection search, inspection detail, station search and record,
and the inspection form's code tables."""

import json
import time

from . import parse, places
from .client import NbtcError, Session
from .dates import to_portal_date

SEARCH_PATH = "/Oper/ISO/11/FF11ChkSch.aspx"
DETAIL_PATH = "/Oper/ISO/11/FF11Chk.aspx"
STATION_PATH = "/Oper/ISO/STN/dSTN.ashx"
STATION_SEARCH_PATH = "/Oper/ISO/STN/mStnSch.aspx"

# A result set that pages unstably is re-walked until every row is seen.
MAX_PASSES = 3
# find_stations' data sources (SrcData) when none is asked for.
DEFAULT_SOURCES = ("BCS", "OPER")


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
        self._form_options = None
        self._alternate = None
        self.clock = time.monotonic  # find_stations' time_limit runs on it

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

    def form_options(self, *, fresh: bool = False) -> dict:
        """The inspection form's code tables: id -> name, with the parent id.

        regions, areas (region_id), source_types, issues (source_type_id),
        inspectors, approvers and test_equipment (area_id), antennas, cables.
        regions and areas hold only the account's own; the area-keyed tables
        hold every area's entries. Read from the blank add form, then kept in
        .nbtc_oper/form_options.json until fresh=True.
        """
        path = self.session.state_dir / "form_options.json"
        if self._form_options is None or fresh:
            if path.is_file() and not fresh:
                self._form_options = json.loads(path.read_text(encoding="utf-8"))
            else:
                add_form = self.session.get(DETAIL_PATH, [("fno", "add")], fresh=fresh)
                options = parse.parse_form_options(add_form)
                if not options["areas"]:
                    raise NbtcError("no inspection form found at FF11Chk.aspx?fno=add")
                self._form_options = options
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(options, ensure_ascii=False), encoding="utf-8")
        return self._form_options

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

    def count_stations(self, *, limit: int = 25, fresh: bool = False, **filters) -> dict:
        """Distinct stations among the matching inspections. Walks every page.

        inspections is the portal's own total, the number its search page shows.
        by_result splits rows by OpinionDet (ตรงตามมาตรฐาน / ไม่ตรงตามมาตรฐาน);
        pass result= to have the portal filter on it instead. station_list names
        up to limit of the stations, latest inspection first, each with what
        that inspection found and how many times the station was inspected.
        """
        result = self.search(fresh=fresh, **filters)
        latest, times = {}, {}
        for row in result["rows"]:
            key = station_key(row)
            times[key] = times.get(key, 0) + 1
            if key not in latest or (row.get("inspected_date") or "") > (latest[key].get("inspected_date") or ""):
                latest[key] = row
        listed = sorted(latest.items(), key=lambda kv: kv[1].get("inspected_date") or "", reverse=True)
        groups = {}
        for row in result["rows"]:
            groups.setdefault(row.get("result") or "", []).append(row)
        return {
            "inspections": result["total"],
            "stations": len({station_key(row) for row in result["rows"]}),
            "by_result": {
                name: {"inspections": len(rows), "stations": len({station_key(r) for r in rows})}
                for name, rows in groups.items()
            },
            "complete": result["complete"],
            "station_list": [
                parse.compact_inspection(row, times[key]) for key, row in listed[:limit]
            ],
            "truncated": len(listed) > limit,
        }

    def station_search(
        self,
        *,
        province=None,
        district=None,
        subdistrict=None,
        max_pages: int | None = None,
        fresh: bool = False,
        deadline: float | None = None,
        **filters,
    ) -> dict:
        """Every register station matching the filters, all pages, deduped on stn_id.

        This is the picker behind the inspection form's station field; unlike
        search() it also lists stations nobody has inspected. `source` is the
        portal's SrcData (ASMS, WEB, BCS, BCS2, BCS3, OPER). See
        build_station_query() for the full filter list. Past deadline (on
        self.clock) no further page is asked for and the result is incomplete.
        """
        if province or district or subdistrict:
            prov, dist, sub = places.resolve(self.places(), province, district, subdistrict)
            filters.update(province_id=prov, district_id=dist, subdistrict_id=sub)
        return self._station_walk(filters, max_pages, fresh, deadline)

    def find_stations(
        self,
        *,
        province=None,
        district=None,
        subdistrict=None,
        frequency=None,
        name=None,
        source=None,
        limit: int = 25,
        details: bool = False,
        fresh: bool = False,
        time_limit: float | None = None,
    ) -> dict:
        """Register stations as short summaries, shaped for a chat model's tool call.

        Any of province / district / frequency / name narrows the search; at
        least one is needed. With no place, only the office's provinces
        (places.OFFICE_PROVINCES: นครราชสีมา, ชัยภูมิ) are searched, one walk
        each, and the result names them in `provinces`. A district without
        its province is looked up across every province, the office's first. frequency matches the portal's way: exactly,
        in MHz. With no source, DEFAULT_SOURCES (BCS, OPER) are searched, one
        walk per province and source. Stations whose
        frequency reads 0.0 are dropped. details=True adds licence, operator
        and coordinates (lat, lng), one request per station shown. With time_limit (seconds), the walk stops
        asking once it runs out and returns what it saw: complete is False and
        total is the portal's own count when it showed one. A request already
        sent still finishes, so the call can run one request past the limit.
        -> {"total", "shown", "truncated", "complete", "stations"}
        """
        deadline = self.clock() + time_limit if time_limit is not None else None
        if not any(v not in (None, "") for v in (province, district, subdistrict, frequency, name)):
            raise ValueError("find_stations needs a province, district, frequency or name")
        anywhere = not (province or district or subdistrict)
        if not anywhere:
            province, district, subdistrict = places.resolve_loose(
                self.places(), province, district, subdistrict
            )
        if frequency not in (None, ""):
            frequency = f"{float(frequency):g}"  # the portal matches "91" but not "91.0"

        provinces = places.OFFICE_PROVINCES if anywhere else (province,)
        sources = (source,) if source else DEFAULT_SOURCES
        plan = [(prov, src) for prov in provinces for src in sources]
        walks = []
        for n, (prov, src) in enumerate(plan):
            share = None  # each walk gets an even part of the time still left
            if deadline is not None:
                share = self.clock() + (deadline - self.clock()) / (len(plan) - n)
            walks.append(self.station_search(
                province=prov,
                district=district,
                subdistrict=subdistrict,
                frequency=frequency or "",
                name=name or "",
                source=src,
                fresh=fresh,
                deadline=share,
            ))
        result = {
            "rows": list({r["stn_id"]: r for w in walks for r in w["rows"]}.values()),
            "complete": all(w["complete"] for w in walks),
            "total": sum(w["total"] or 0 for w in walks) if any(w["total"] for w in walks) else None,
        }
        rows = [r for r in result["rows"] if r.get("frequency_mhz") != 0.0]
        rows.sort(key=lambda r: (r.get("frequency_mhz") is None, r.get("frequency_mhz") or 0, r.get("name") or ""))
        shown = rows[:limit]
        stations = [
            parse.compact_station(
                r,
                self.station(r["stn_id"], fresh=fresh)
                if details and not self._out_of_time(deadline) else None,
            )
            for r in shown
        ]
        total = len(rows) if result["complete"] else max(result["total"] or 0, len(rows))
        return {
            "total": total,
            "shown": len(stations),
            "truncated": len(stations) < total,
            "complete": result["complete"],
            **({"provinces": [places.bare(self.places()["provinces"][p]) for p in places.OFFICE_PROVINCES]}
               if anywhere else {}),
            "stations": stations,
        }

    def _out_of_time(self, deadline) -> bool:
        return deadline is not None and self.clock() >= deadline

    def _station_walk(self, filters, max_pages, fresh, deadline=None) -> dict:
        """Walk the picker; if paging loses rows, re-ask one place level down.

        The picker orders its pages unstably, so a station can repeat on several
        pages while another never shows. A slice small enough for one page has
        no such gap, so an incomplete result is filled in province by province,
        then district by district, then sub-district by sub-district.
        """
        query = build_station_query(**filters)
        result = self._walk(
            STATION_SEARCH_PATH, query, parse.parse_station_search_page, "stn_id", max_pages, fresh,
            deadline,
        )
        if result["complete"] or max_pages is not None or result["total"] is None:
            return result
        if self._out_of_time(deadline):
            return result
        rows = {row["stn_id"]: row for row in result["rows"]}
        for narrower in self._narrower(filters, query):
            if len(rows) >= result["total"] or self._out_of_time(deadline):
                break
            for row in self._station_walk({**filters, **narrower}, None, fresh, deadline)["rows"]:
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

    def _walk(self, path, query, parse_page, key, max_pages, fresh, deadline=None) -> dict:
        rows, total, pages = {}, None, 1
        for attempt in range(MAX_PASSES):
            page = 1
            while page <= pages and (max_pages is None or page <= max_pages):
                if self._out_of_time(deadline):
                    break
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
            if self._out_of_time(deadline):
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
