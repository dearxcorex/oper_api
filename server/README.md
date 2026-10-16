# HTTP wrapper

`server/app.py` exposes `find_stations` and `count_stations` over HTTP for
fm-station-tracker's Discord `/ask` bot. It runs on a Raspberry Pi at home and
is reached through Tailscale Funnel: Cloudflare challenges the portal from cloud
IPs (a Vercel deploy got HTTP 403 on every request), but lets a home IP through.

Read-only, and never returns coordinates. One portal session serves every
request, one at a time.

| Route | Auth | Body |
|---|---|---|
| `GET /health` | none | — never touches the portal; answers `ok`, `as_of` (the saved register's build time, or null) and `refreshing` |
| `POST /find-stations` | bearer | `province`, `district`, `subdistrict`, `frequency`, `name`, `source`, `limit`, `details` |
| `POST /count-stations` | bearer | `inspected_from`, `inspected_to` (ISO dates), `province`, `district`, `result` |
| `POST /refresh` | bearer | — starts a register rebuild in the background: 202, or 409 `busy` if one is already running |

`/find-stations` answers from the saved station register when there is one
and it covers the province asked about (นครราชสีมา and ชัยภูมิ; a search with
no place gets those two, named in `provinces`). Every source is walked
separately, deduped on StnID, with each station's licence and operator, so
`details` is free and the reply carries `as_of` (the build time). Otherwise the
portal is walked live for at most 20 seconds (the bot gives a tool call about
30): a walk cut short answers `complete: false`, with `total` the portal's own
count, and `details` is capped at 10.

The copy is rebuilt every night at 03:00 by `oper-api-register.timer`, or on
demand with `POST /refresh` (about 30 minutes either way). A lock file keeps the
two from running at once. A build where any data source comes back incomplete
fails and leaves the previous copy in place; the timer's failures show in
`journalctl -u oper-api-register`, a refresh's in `journalctl -u oper-api`.
A refresh uses its own portal login, so questions keep being answered while it
runs. To build by hand:

```bash
uv run python -m nbtc_oper register     # writes .nbtc_oper/register.json
```

`/count-stations` answers `inspections` (the portal's own total), `stations`
(distinct), and `by_result`: both counts per result. `result` is
`ตรงตามมาตรฐาน` or `ไม่ตรงตามมาตรฐาน` and filters on the portal side.

Errors come back as `{"error", "detail"}`: `cloudflare` 503, `login_failed` 502,
`portal` 502, `unknown_place` / `bad_input` 400.

```bash
OPER_API_TOKEN=dev uv run --group server uvicorn server.app:app --host 127.0.0.1 --port 8787
```

## Raspberry Pi setup

64-bit Raspberry Pi OS, user `raspi`.

```bash
sudo apt update && sudo apt install -y git curl
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/dearxcorex/oper_api.git ~/oper_api
cd ~/oper_api && uv sync --frozen --group server

mkdir -p ~/.config/oper-api && touch ~/.config/oper-api/env && chmod 600 ~/.config/oper-api/env
nano ~/.config/oper-api/env    # NBTC_USERNAME=…  NBTC_PASSWORD=…  OPER_API_TOKEN=<openssl rand -hex 32>

sudo cp server/oper-api.service server/oper-api-register.service server/oper-api-register.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now oper-api oper-api-register.timer
sudo systemctl start --no-block oper-api-register   # the first register build, ~30 min
curl http://127.0.0.1:8787/health
```

The timer fires at 03:00 in the Pi's time zone (`sudo timedatectl set-timezone Asia/Bangkok`);
`systemctl list-timers oper-api-register` shows the next run.

Tailscale Funnel (needs HTTPS and Funnel turned on for the tailnet in the admin console):

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale funnel --bg 8787
tailscale funnel status          # the public https://<host>.<tailnet>.ts.net URL
```

fm-station-tracker then needs `OPER_API_URL` (that URL) and `OPER_API_TOKEN`.

Updates: `ssh` in and run `./server/deploy.sh` (it reinstalls the units too).
