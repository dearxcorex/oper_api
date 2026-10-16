"""nbtc-oper: run a search or fetch a record and write it as JSON.

    uv run python -m nbtc_oper search --from 2026-01-01 --province นครราชสีมา
    uv run python -m nbtc_oper inspection 52390
    uv run python -m nbtc_oper station 19363
    uv run python -m nbtc_oper stations --province ชัยภูมิ --source OPER
    uv run python -m nbtc_oper search --reported-from 2026-01-01 --source-type-id 2 --count
    uv run python -m nbtc_oper register    # save the station register for find_stations
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from . import config, register
from .api import NbtcOper
from .client import NbtcError
from .config import CredentialsNotFound
from .places import UnknownPlace


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m nbtc_oper", description=__doc__.splitlines()[0])
    p.add_argument("-o", "--output", help="output file; '-' for stdout (default: out/<name>.json)")
    p.add_argument("--fresh", action="store_true", help="bypass the 15-minute response cache")
    p.add_argument("--ver-id", default="2", help="login data version (default 2: Nov 2020 onward)")
    p.add_argument("--no-raw", action="store_true", help="drop the untranslated 'raw' fields")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", help="inspection search (FF11ChkSch.aspx)")
    s.add_argument("--from", dest="inspected_from", metavar="DATE", help="inspected on/after (ISO)")
    s.add_argument("--to", dest="inspected_to", metavar="DATE", help="inspected on/before (ISO)")
    s.add_argument("--recorded-from", metavar="DATE")
    s.add_argument("--recorded-to", metavar="DATE")
    s.add_argument("--reported-from", metavar="DATE")
    s.add_argument("--reported-to", metavar="DATE")
    s.add_argument("--province", help="Thai name or code")
    s.add_argument("--district", help="Thai name or code (needs --province)")
    s.add_argument("--subdistrict", help="Thai name or code (needs --district)")
    s.add_argument("--station-name")
    s.add_argument("--licence-no")
    s.add_argument("--freq-from", type=float)
    s.add_argument("--freq-to", type=float)
    s.add_argument("--result", help="e.g. ตรงตามมาตรฐาน / ไม่ตรงตามมาตรฐาน")
    s.add_argument("--source-type-id", type=int, default=0)
    s.add_argument("--unlicensed-only", action="store_true")
    s.add_argument("--region-id", type=int, default=5)
    s.add_argument("--area-id", type=int, default=8)
    s.add_argument("--station-type-id", type=int, default=4)
    s.add_argument("--max-pages", type=int)
    s.add_argument("--count", action="store_true",
                   help="print only the portal's result total (1 request, no file)")
    s.add_argument("--count-stations", action="store_true",
                   help="print only how many distinct stations the inspections cover (walks every page)")
    s.add_argument("--details", action="store_true",
                   help="also fetch each inspection's detail and station (2 requests per row)")

    i = sub.add_parser("inspection", help="one inspection by ChkID")
    i.add_argument("chk_id", type=int)

    t = sub.add_parser("station", help="one station record by StnID")
    t.add_argument("stn_id", type=int)

    n = sub.add_parser("stations", help="station register search (STN/mStnSch.aspx)")
    n.add_argument("--name", help="station name contains")
    n.add_argument("--frequency", metavar="FREQ")
    n.add_argument("--location", help="address contains")
    n.add_argument("--site-code")
    n.add_argument("--licence-no")
    n.add_argument("--source", choices=["ASMS", "WEB", "BCS", "BCS2", "BCS3", "OPER"],
                   help="the register's data source (default: all)")
    n.add_argument("--province", help="Thai name or code")
    n.add_argument("--district", help="Thai name or code (needs --province)")
    n.add_argument("--subdistrict", help="Thai name or code (needs --district)")
    n.add_argument("--area-id", type=int, default=8)
    n.add_argument("--station-type-id", type=int, default=4)
    n.add_argument("--station-subtype-id", type=int, default=0)
    n.add_argument("--max-pages", type=int)
    n.add_argument("--count", action="store_true",
                   help="print only the portal's result total (1 request, no file)")
    r = sub.add_parser("register", help="save the whole station register (.nbtc_oper/register.json)")
    r.add_argument("--area-id", type=int, default=8)
    r.add_argument("--station-type-id", type=int, default=4)
    return p


def _strip_raw(value):
    if isinstance(value, dict):
        return {k: _strip_raw(v) for k, v in value.items() if k != "raw"}
    if isinstance(value, list):
        return [_strip_raw(v) for v in value]
    return value


def _run(args) -> tuple[str, object]:
    api = NbtcOper(ver_id=args.ver_id)
    if args.command == "inspection":
        return f"inspection-{args.chk_id}", api.inspection(args.chk_id, fresh=args.fresh)
    if args.command == "station":
        return f"station-{args.stn_id}", api.station(args.stn_id, fresh=args.fresh)
    if args.command == "register":
        path = register.path_for(api)
        copy = register.rebuild(api, path, area_id=args.area_id, station_type_id=args.station_type_id)
        print(
            f"{len(copy['stations'])} station(s) {copy['counts']}, "
            f"{api.requests_sent} request(s) sent, wrote {path}",
            file=sys.stderr,
        )
        return "register", None

    skip = {"command", "output", "fresh", "ver_id", "no_raw", "details", "count", "count_stations"}
    filters = {k: v for k, v in vars(args).items() if k not in skip and v is not None}
    if args.count:
        # Page 1 carries the portal's own total; one request.
        filters["max_pages"] = 1
        walk = api.station_search if args.command == "stations" else api.search
        return "count", walk(fresh=args.fresh, **filters)["total"]
    if args.command == "search" and args.count_stations:
        filters.pop("max_pages", None)
        counted = api.count_stations(fresh=args.fresh, **filters)
        print(
            f"{counted['stations']} station(s) in {counted['inspections']} inspection(s), "
            f"complete={counted['complete']}, {api.requests_sent} request(s) sent",
            file=sys.stderr,
        )
        return "count", counted["stations"]
    if args.command == "stations":
        result = api.station_search(fresh=args.fresh, **filters)
    else:
        result = api.search(fresh=args.fresh, **filters)
    if args.command == "search" and args.details:
        for n, row in enumerate(result["rows"], 1):
            print(f"  detail {n}/{len(result['rows'])} ChkID {row['chk_id']}", file=sys.stderr)
            try:
                row["detail"] = api.inspection(row["chk_id"], fresh=args.fresh)
            except NbtcError as exc:
                row["detail"], row["detail_error"] = None, str(exc)
                print(f"    skipped: {exc}", file=sys.stderr)
    print(
        f"{len(result['rows'])} of {result['total']} rows, {result['pages']} page(s), "
        f"complete={result['complete']}, {api.requests_sent} request(s) sent",
        file=sys.stderr,
    )
    return f"{args.command}-{datetime.now():%Y%m%d-%H%M%S}", result


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        name, data = _run(args)
    except (NbtcError, CredentialsNotFound, UnknownPlace) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.command == "register":
        return 0
    if getattr(args, "count", False) or getattr(args, "count_stations", False):
        if data is None:
            print("error: the portal showed no result total", file=sys.stderr)
            return 1
        print(data)
        return 0
    if args.no_raw:
        data = _strip_raw(data)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if args.output == "-":
        print(text)
        return 0
    path = Path(args.output) if args.output else config.PROJECT_ROOT / "out" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    print(f"wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
