# HTTP wrapper

`server/app.py` exposes `find_stations` and `count_stations` over HTTP for
fm-station-tracker's Discord `/ask` bot. It runs on a Raspberry Pi at home and
is reached through Tailscale Funnel: Cloudflare challenges the portal from cloud
IPs (a Vercel deploy got HTTP 403 on every request), but lets a home IP through.

Read-only, and never returns coordinates. One portal session serves every
request, one at a time.

| Route | Auth | Body |
|---|---|---|
| `GET /health` | none | — never touches the portal |
| `POST /find-stations` | bearer | `province`, `district`, `subdistrict`, `frequency`, `name`, `source`, `limit`, `details` |
| `POST /count-stations` | bearer | `inspected_from`, `inspected_to` (ISO dates), `province`, `district` |

Errors come back as `{"error", "detail"}`: `cloudflare` 503, `login_failed` 502,
`portal` 502, `unknown_place` / `bad_input` 400.

```bash
OPER_API_TOKEN=dev uv run --group server uvicorn server.app:app --host 127.0.0.1 --port 8787
```

## Raspberry Pi setup

64-bit Raspberry Pi OS, user `deardevx`.

```bash
sudo apt update && sudo apt install -y git curl
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/dearxcorex/oper_api.git ~/oper_api
cd ~/oper_api && uv sync --frozen --group server

mkdir -p ~/.config/oper-api && touch ~/.config/oper-api/env && chmod 600 ~/.config/oper-api/env
nano ~/.config/oper-api/env    # NBTC_USERNAME=…  NBTC_PASSWORD=…  OPER_API_TOKEN=<openssl rand -hex 32>

sudo cp server/oper-api.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now oper-api
curl http://127.0.0.1:8787/health
```

Tailscale Funnel (needs HTTPS and Funnel turned on for the tailnet in the admin console):

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale funnel --bg 8787
tailscale funnel status          # the public https://<host>.<tailnet>.ts.net URL
```

fm-station-tracker then needs `OPER_API_URL` (that URL) and `OPER_API_TOKEN`.

Updates: `ssh` in and run `./server/deploy.sh`.
