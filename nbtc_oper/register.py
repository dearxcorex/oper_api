"""A saved copy of the station register, so find_stations needs no portal requests.

Walking the picker live takes over a minute for a district (it re-asks place by
place when paging drops rows), more than a chat bot can wait. build() walks it
once per data source in SOURCES, deduped on StnID: the per-source totals add up
to more than the unfiltered total, so the unfiltered walk can't be trusted to
see every station. Only BCS and OPER are kept; a search for another source is
not covered and goes to the portal. Only the office's provinces are kept (places.OFFICE_PROVINCES); a search
elsewhere is not covered and goes to the portal. Each station's dSTN record supplies its place codes (PATCode) and the
licence and operator that find_stations' details=True shows, and its
coordinates (lat, lng) and its coordinator's name and phone (CoopNa, CoopTel,
what the add-inspection form fills in when a station is picked), all shown on
every summary. OPER stations mostly have a phone there; BCS stations mostly don't.

rebuild() is build() then save(), under a lock file so the monthly timer and an
on-demand refresh never run at once; a build that fails leaves the last good
copy in place.
"""

import fcntl
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import parse, places
from .api import DEFAULT_SOURCES
from .client import NbtcError

SOURCES = DEFAULT_SOURCES  # the portal also has ASMS, WEB, BCS2, BCS3
DETAIL_KEYS = ("licence_no", "licence_expires", "operator", "nbtc_code", "station_id")
CONTACT_KEYS = ("contact_name", "contact_phone", "contact_date")
FILE_NAME = "register.json"


class Busy(NbtcError):
    """Another rebuild holds the lock."""


def path_for(api) -> Path:
    return api.session.state_dir / FILE_NAME


class BuildLock:
    """An exclusive, non-blocking lock beside the copy, held for a whole rebuild.

    flock is per open file, so it also keeps two threads of one process apart,
    and the kernel drops it if the holder dies.
    """

    def __init__(self, path: Path):
        self.path = path.with_suffix(".lock")
        self._fd = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise Busy("a register rebuild is already running") from None
        self._fd = fd

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


def rebuild(api, path: Path | None = None, *, lock: BuildLock | None = None, log=None, **options) -> dict:
    """build() and save() over the copy at path, holding its lock.

    Pass a lock already acquired to have rebuild() release it when done.
    Raises Busy when another rebuild holds the lock; any build error propagates
    and the old copy stays.
    """
    path = path or path_for(api)
    if lock is None:
        lock = BuildLock(path)
        lock.acquire()
    try:
        copy = build(api, log=log, **options)
        save(copy, path)
        return copy
    finally:
        lock.release()


def build(api, *, sources=SOURCES, provinces=places.OFFICE_PROVINCES, area_id: int = 8, station_type_id: int = 4, log=None) -> dict:
    """Walk the register source by source, keep the given provinces, and fetch each station's record.

    Each source is walked across the whole area: walks filtered by province
    come back short of the portal's count, while the area-wide ones complete.
    A station whose address names another province is dropped before its
    record is fetched; the rest are kept by PATCode, or by address when the
    record has none. Raises NbtcError when any walk comes back incomplete, so
    a partial copy is never mistaken for the register.
    """
    log = log or (lambda msg: print(msg, file=sys.stderr))
    wanted = {p: places.bare(api.places()["provinces"][p]) for p in provinces}
    rows, counts, seen_in = {}, {}, {}
    for source in sources:
        result = api.station_search(
            source=source, area_id=area_id, station_type_id=station_type_id, fresh=True
        )
        if not result["complete"]:
            raise NbtcError(
                f"source {source}: {len(result['rows'])} of {result['total']} stations seen"
            )
        counts[source] = len(result["rows"])
        for row in result["rows"]:
            rows.setdefault(row["stn_id"], row)
            seen_in.setdefault(row["stn_id"], []).append(source)
        log(f"{source}: {counts[source]} station(s), {api.requests_sent} request(s) so far")

    named = {sid: parse.split_location(row.get("location"))["province"] for sid, row in rows.items()}
    todo = [row for sid, row in rows.items() if named[sid] is None or places.bare(named[sid]) in wanted.values()]
    log(f"{len(todo)} of {len(rows)} station(s) may be in {', '.join(wanted.values())}")
    stations = []
    for n, row in enumerate(todo, 1):
        if n % 50 == 0:
            log(f"records {n}/{len(todo)}")
        entry = _entry(row, _record(api, row["stn_id"]))
        entry["sources"] = seen_in[row["stn_id"]]
        if entry["pat_code"] and entry["pat_code"][:2] not in wanted:
            continue
        if not entry["pat_code"] and named[row["stn_id"]] is None:
            continue  # no place at all: cannot say it is in either province
        stations.append(entry)
    return {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "area_id": area_id,
        "station_type_id": station_type_id,
        "provinces": list(provinces),
        "counts": counts,
        "stations": stations,
    }


def _record(api, stn_id) -> dict | None:
    """The station's dSTN record, from whichever login version holds it."""
    for session in (api.session, api._alternate_session()):
        try:
            return api.station(stn_id, fresh=True, _session=session)
        except NbtcError:
            continue
    return None


def _entry(row: dict, record: dict | None) -> dict:
    entry = parse.compact_station(row, record or {})
    pat = str((record or {}).get("pat_code") or "").strip()
    entry["pat_code"] = pat if len(pat) == 6 and pat.isdigit() else None
    if record is None:
        entry.update(dict.fromkeys(DETAIL_KEYS + ("lat", "lng")))
    phone = (record or {}).get("contact_phone")
    entry["contact_name"] = (record or {}).get("contact_name") if phone else None
    entry["contact_phone"] = phone
    entry["contact_date"] = (record or {}).get("updated_at") if phone else None
    return entry


def save(copy: dict, path: Path) -> None:
    """Write atomically: a reader sees the old copy or the new one, never half."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(copy, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def covers(
    copy: dict, gazetteer: dict, *, province=None, district=None, subdistrict=None, source=None, **_
) -> bool:
    """Whether the copy can answer a search: sources it walked (BCS and OPER when
    none is named), and no place or a province it was built for."""
    if not set((source,) if source else DEFAULT_SOURCES) <= copy["counts"].keys():
        return False
    if "provinces" not in copy:
        return True  # built before the province limit: the whole area
    prov = places.resolve_loose(gazetteer, province, district, subdistrict)[0]
    return prov == "0" or prov in copy["provinces"]


def find(
    copy: dict,
    gazetteer: dict,
    *,
    province=None,
    district=None,
    subdistrict=None,
    frequency=None,
    name=None,
    source=None,
    limit: int = 25,
    details: bool = False,
) -> dict:
    """find_stations() over the copy: same filters, same result shape, plus as_of.

    A search with no place covers only the copy's provinces, named in `provinces`;
    with no source, BCS and OPER.
    """
    wanted = {source} if source else set(DEFAULT_SOURCES)
    prov, dist, sub = places.resolve_loose(gazetteer, province, district, subdistrict)
    code = next((c for c in (sub, dist, prov) if c != "0"), None)
    names = {
        "province": _place_name(gazetteer["provinces"].get(prov)),
        "district": _place_name(gazetteer["districts"].get(prov, {}).get(dist)),
        "subdistrict": _place_name(gazetteer["subdistricts"].get(dist, {}).get(sub)),
    }
    freq = round(float(frequency), 3) if frequency not in (None, "") else None
    needle = (name or "").strip().casefold()

    def matches(s):
        if code and not _in_place(s, code, names):
            return False
        if freq is not None and (s.get("frequency_mhz") is None or round(s["frequency_mhz"], 3) != freq):
            return False
        if needle and needle not in (s.get("name") or "").casefold():
            return False
        return not wanted.isdisjoint(s.get("sources") or [s.get("source")])

    rows = [s for s in copy["stations"] if s.get("frequency_mhz") != 0.0 and matches(s)]
    rows.sort(key=lambda r: (r.get("frequency_mhz") is None, r.get("frequency_mhz") or 0, r.get("name") or ""))
    shown = [_summary(s, details) for s in rows[:limit]]
    return {
        "total": len(rows),
        "shown": len(shown),
        "truncated": len(shown) < len(rows),
        "complete": True,
        "as_of": copy["built_at"],
        **({"provinces": [_place_name(gazetteer["provinces"].get(p)) or p for p in copy["provinces"]]}
           if "provinces" in copy and code is None else {}),
        "stations": shown,
    }


def _place_name(name):
    return places.bare(name) if name else None


def _in_place(station: dict, code: str, names: dict) -> bool:
    """By PATCode when the record had one, else by the names in its address."""
    if station.get("pat_code"):
        return station["pat_code"].startswith(code)
    return all(
        want is None or places.bare(station.get(level) or "") == want
        for level, want in names.items()
    )


def _summary(station: dict, details: bool) -> dict:
    out = {k: v for k, v in station.items() if k not in ("pat_code", "sources")}
    if not details:
        for key in DETAIL_KEYS:
            out.pop(key, None)
    return out
