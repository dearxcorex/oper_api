#!/usr/bin/env bash
# Update the wrapper on the Pi: pull, sync, restart, check.
# Run on the Pi from the repo root: ./server/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

git pull --ff-only
uv sync --frozen --group server
sudo systemctl restart oper-api
sleep 3
curl -fsS http://127.0.0.1:8787/health && echo
