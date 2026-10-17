# NBTC OPER API reference

The field types are in `operClient.ts`. This file covers what the types can't say.

The API is a read-only wrapper around the NBTC OPER portal (`fmr.nbtc.go.th/Oper`)
for broadcast stations in เขต 23. It runs on a home machine because Cloudflare
blocks the portal from cloud IPs. Behind it is a single portal session that
answers one request at a time, so callers should queue their requests rather
than fan them out.

## Routes

| Route | Auth | Body |
|---|---|---|
| `GET /health` | none | — never touches the portal; answers `ok`, `as_of` (the saved register's build time, or null) and `refreshing` |
| `POST /find-stations` | bearer | `province`, `district`, `subdistrict`, `frequency`, `name`, `source`, `limit`, `details` |
| `POST /count-stations` | bearer | `inspected_from`, `inspected_to` (ISO dates), `province`, `district`, `result`, `limit` |
| `POST /refresh` | bearer | — starts a register rebuild in the background: 202, or 409 `busy` if one is already running |

Bearer means `Authorization: Bearer $OPER_API_TOKEN`. Unknown body fields are
rejected with a 422.

## Places

Places are Thai names with or without the prefix (`ชัยภูมิ` and `จ.ชัยภูมิ` both
work), or the portal's numeric codes. A district can be given without its
province: it is looked up in every province, and when the name appears in
several provinces, นครราชสีมา or ชัยภูมิ wins. A sub-district needs its district.

## `/find-stations`

This searches the station register, inspected or not. It needs at least one of
`province`, `district`, `frequency` or `name`. `frequency` is an exact match in
MHz, `name` is a substring match, and stations whose frequency reads 0.0 are
dropped. `limit` (1–100, default 25) caps `stations`, while `total` still
counts every match. With no `source`, BCS and OPER are searched together.

The answer comes from one of two places:

- **The saved copy.** This is used for BCS and OPER (or no `source`) in นครราชสีมา (30) and ชัยภูมิ (36),
  and for a search with no place, which gets those two provinces, named in
  `provinces`. Answers come back instantly with `complete: true` and `as_of`
  set to the build time. Every station carries `lat`/`lng` and
  `contact_name`/`contact_phone`/`contact_date` (the coordinator on its
  station record, and the date that record was last updated; mostly null for
  BCS stations). `details` is free. The copy is rebuilt on the
  1st of each month.
- **A live portal walk.** This is used for anywhere else, or any other
  `source`. The walk is cut off at 20 seconds. A walk cut short answers
  `complete: false`, `total` is then the portal's own count, and you must
  tell the user the list is partial. `details` adds one portal request per
  station and is capped at 10 stations. There are no contacts, and `lat`/`lng`
  appear only with `details`.

`details: true` adds `licence_no`, `licence_expires`, `operator`, `nbtc_code`
and `station_id`. Any of these can be null, and so can `lat`/`lng` (the
portal's blanks and zeros come back as null).

## `/count-stations`

This counts inspections between two dates, inclusive. `inspections` is the
portal's own total, the number its search page shows. `stations` is the
number of distinct stations among those inspections. `by_result` splits both
counts by result. `result` filters on the portal side. `station_list` names
up to `limit` (default 25, max 100) of those stations, latest inspection
first: name, frequency, code, licence, place, that inspection's date, result
and warning document, and `inspections`, how many times it was inspected in
the range. `truncated` says some stations were left out. Every page is walked,
so a long date range can take longer than the 30 s client timeout; narrow the
dates when it does.

## Errors

The body is `{error, detail}`:

| `error` | Status | Meaning |
|---|---|---|
| `unknown_place` | 400 | a place name didn't resolve; `detail` says which, so fix the name and retry |
| `bad_input` | 400 | for example, `inspected_to` is before `inspected_from` |
| `cloudflare` | 503 | the portal challenged the home machine; retry later |
| `login_failed` | 502 | the portal refused the server's credentials; tell the API owner |
| `portal` | 502 | the portal answered something unexpected |
| `busy` | 409 | `/refresh` while a rebuild is running |

FastAPI's own 401 (bad token) and 422 (bad body) carry only `detail`, which
`operClient.ts` reports as `http_401` / `http_422`.
