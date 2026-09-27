#!/usr/bin/env bash
# Поднять demo SiteWatch: seed + FastAPI/React :8000
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

if [[ ! -f "$ROOT/frontend/dist/index.html" ]]; then
  (cd "$ROOT/frontend" && npm install && npm run build)
fi

sitewatch seed-demo

if ss -ltn 2>/dev/null | grep -q ':8000 '; then
  echo "UI already on :8000"
else
  nohup sitewatch ui >/tmp/sitewatch-ui.log 2>&1 &
  echo "UI pid $!"
fi

echo "UI  http://127.0.0.1:8000"
echo "API http://127.0.0.1:8000/api/health"
