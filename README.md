# nbtc-oper

Python client for the NBTC OPER inspection search at `fmr.nbtc.go.th/Oper`
(`ISO/11/FF11ChkSch.aspx`). Plain HTTP through `curl_cffi` impersonating
Chrome — no browser. The portal has no public API; this drives the same
requests its own pages make.

## Setup

Credentials come from the environment, then `./.env`, then `$NBTC_ENV_FILE`
(`NBTC_USER`/`NBTC_USERNAME` and `NBTC_PASS`/`NBTC_PASSWORD`). Never in code.

```bash
uv sync
uv run pytest            # parser tests on saved pages, no network
```

## CLI

Run from this directory. Output goes to `out/` unless `-o` says otherwise
(`-o -` for stdout).

```bash
uv run python -m nbtc_oper search --from 2026-01-01
uv run python -m nbtc_oper search --from 2026-01-01 --province ชัยภูมิ --district เมืองชัยภูมิ
uv run python -m nbtc_oper search --from 2026-01-01 --details   # + detail and station per row
uv run python -m nbtc_oper inspection 52390
uv run python -m nbtc_oper station 19363
uv run python -m nbtc_oper stations --province ชัยภูมิ --source OPER   # station register search
uv run python -m nbtc_oper search --reported-from 2026-01-01 --source-type-id 2 --count   # just the total
uv run python -m nbtc_oper search --reported-from 2026-01-01 --source-type-id 2 --count-stations   # distinct stations
```

## Library

```python
from nbtc_oper import NbtcOper

api = NbtcOper()
result = api.search(inspected_from="2026-01-01", province="นครราชสีมา")
result["total"], result["complete"], result["rows"][0]["chk_id"]
detail = api.inspection(52390)        # lat, lng, station_id, nbtc_code, station{…}
station = api.station(19363)
stations = api.station_search(province="ชัยภูมิ", source="OPER")   # rows keyed by stn_id
api.search(reported_from="2026-01-01", source_type_id=2, max_pages=1)["total"]   # the portal's own total, 1 request
options = api.form_options()          # code tables: areas, issues, inspectors, test_equipment, …
api.find_stations(district="ภูเขียว", source="BCS")   # short summaries for a chat model
api.find_stations(frequency=91.75, details=True)     # + licence, expiry, operator
```

`nbtc_oper.llm` holds the same search as a tool definition in the Anthropic
Messages format (`FIND_STATIONS_TOOL`, `TOOLS`) and `run_tool(api, name, input)`
to dispatch a call.

Dates are ISO in and out; the portal's Buddhist-era `dd/mm/yyyy` is converted
at the edge. Places are Thai names (prefix optional) or portal codes. Every
record keeps the untranslated portal fields under `raw`.

## Behaviour

- **Session.** Logs in on first use, keeps cookies in `.nbtc_oper/cookies.json`,
  and signs in again once if a response redirects to `Login.aspx`.
- **Pace.** One request at a time, at least 1.5 s apart.
- **Cache.** Responses are reused for 15 minutes (`.nbtc_oper/cache/`);
  `--fresh` / `fresh=True` bypasses it.
- **Paging.** `search()` walks every page and dedupes on `chk_id`. If it ends
  up short of the portal's own total it re-walks, up to 3 passes, and reports
  `complete`.
- **Versions.** The portal has two login modes (`VerID`). An inspection whose
  station carries a legacy numeric code opens only under `VerID=1`; under the
  default `VerID=2` the detail page comes back as an empty 200. `inspection()`
  then retries under the other version (its own login, cookies and cache in
  `.nbtc_oper/ver1/`) and reports which one answered as `ver_id`.
- **Details.** `search --details` records a row it cannot open as
  `detail: null` plus `detail_error` and carries on.
- **Cloudflare.** A managed challenge raises `CloudflareChallenge`; there is
  no browser fallback.
- **Stations.** `station_search()` / `stations` is the picker behind the
  inspection form's station field (`STN/mStnSch.aspx`). It lists the whole
  register, inspected or not; `source` is the portal's `SrcData` column
  (`ASMS`, `WEB`, `BCS`, `BCS2`, `BCS3`, `OPER`). Rows carry no coordinates —
  call `station(stn_id)` for the full record. The picker pages unstably
  (a station repeats across pages while another never shows), so a result
  still short after the re-walks is filled in one place level down: by
  province, then district, then sub-district.
- **Form options.** `form_options()` reads the code tables out of the blank
  add form (`FF11Chk.aspx?fno=add`, never submitted) and keeps them in `.nbtc_oper/form_options.json` until `fresh=True`.
- **Chat summaries.** `find_stations()` wraps `station_search()` for a chat
  model: it needs at least one of province, district, frequency or name; a
  district alone is looked up across every province; frequency is the portal's
  exact match in MHz; stations whose frequency reads 0.0 are dropped. Each
  station is a short summary (place split into sub-district/district/province)
  with no coordinates and no `raw`; `limit` caps how many come back while
  `total` still counts them all.
- **Counts.** `--count` / `search(max_pages=1)["total"]` reads the portal's own total from page 1
  and counts inspections. `--count-stations` / `count_stations()` walks every
  page and counts distinct stations: by station code, or by name, frequency
  and licence number for a row that has no code. Its `by_result` splits both
  counts by result (ตรงตามมาตรฐาน / ไม่ตรงตามมาตรฐาน); `result=` filters on the portal side.
- **Scope.** The inspection search only lists stations somebody has inspected. `RegID=5`,
  `AreaID=8` (เขต 23) and `StnTypeID=4` (สถานีวิทยุกระจายเสียง) are defaults.
