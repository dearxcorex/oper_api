#!/usr/bin/env bash
# Update the wrapper on the Pi: pull, sync, reinstall the units, restart, check.
# Run on the Pi from the repo root: ./server/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

git pull --ff-only
uv sync --frozen --group server
sudo cp server/oper-api.service server/oper-api-register.service server/oper-api-register.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now oper-api-register.timer
sudo systemctl restart oper-api
sleep 3
curl -fsS http://127.0.0.1:8787/health && echo
