# HTTP wrapper

`server/app.py` exposes `find_stations` and `count_stations` over HTTP for
fm-station-tracker's Discord `/ask` bot. It runs on a Raspberry Pi at home and
is reached through Tailscale Funnel: Cloudflare challenges the portal from cloud
IPs (a Vercel deploy got HTTP 403 on every request), but lets a home IP through.

Read-only. One portal session serves every
request, one at a time.

The routes, request and response fields, and errors are in
[`skills/oper-api/REFERENCE.md`](../skills/oper-api/REFERENCE.md), the `oper-api`
skill that connects a project to this API; its `operClient.ts` is the typed
client, checked against `app.py` by `tests/test_skill_client.py`.

`/find-stations` answers from the saved station register when it covers the
search, and walks the portal live for at most 20 seconds otherwise.

The saved register is rebuilt at 03:00 on the 1st of every month by `oper-api-register.timer`, or on
demand with `POST /refresh` (about 30 minutes either way). A lock file keeps the
two from running at once. Only the BCS data source is saved, with each station's
contact phone from its latest inspection. A build whose walk comes back incomplete
fails and leaves the previous copy in place; the timer's failures show in
`journalctl -u oper-api-register`, a refresh's in `journalctl -u oper-api`.
A refresh uses its own portal login, so questions keep being answered while it
runs. To build by hand:

```bash
uv run python -m nbtc_oper register     # writes .nbtc_oper/register.json
```

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

The timer fires at 03:00 on the 1st in the Pi's time zone (`sudo timedatectl set-timezone Asia/Bangkok`);
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
