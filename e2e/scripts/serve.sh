#!/usr/bin/env bash
# Starts paperus for the end-to-end tests: a fresh database, the worker and
# the API (which serves the built website from web/build). Playwright runs
# this as its web server and stops it after the tests.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PORT=${PAPERUS_E2E_PORT:-8100}

export PAPERUS_DATABASE_URL=${PAPERUS_E2E_DATABASE_URL:-postgresql+psycopg://paperus:paperus@localhost:5432/paperus_e2e}
STATE=$(mktemp -d -t paperus-e2e.XXXXXX)
export PAPERUS_STORAGE_PATH=$STATE/files
export PAPERUS_BACKUP_PATH=$STATE/backups
export PAPERUS_COPY_PATH=$STATE/library-copy
export PAPERUS_WEB_PATH=$ROOT/web/build
# Plain HTTP on localhost.
export PAPERUS_COOKIE_SECURE=false
# No ML service: search falls back to keywords. A closed port, so a dev
# ML service on its default port is never used (PAPERUS_E2E_ML_URLS: one to
# try the ML settings against).
export PAPERUS_ML_URLS=${PAPERUS_E2E_ML_URLS:-'["http://127.0.0.1:9"]'}

if [ ! -f "$PAPERUS_WEB_PATH/200.html" ]; then
  echo "web/build is missing: run 'npm --prefix web run build' first" >&2
  exit 1
fi

pids=()
cleanup() {
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  rm -rf "$STATE"
}
trap cleanup EXIT
trap 'exit 0' INT TERM

uv --directory "$ROOT/server" run python "$ROOT/e2e/scripts/reset_db.py"
uv --directory "$ROOT/server" run paperus migrate
# Their logs go to a file (the worker's retries without ML are noisy).
LOGS=${PAPERUS_E2E_LOGS:-$ROOT/e2e/server-logs}
mkdir -p "$LOGS"
uv --directory "$ROOT/server" run paperus worker >"$LOGS/worker.log" 2>&1 &
pids+=($!)
uv --directory "$ROOT/server" run paperus serve --host 127.0.0.1 --port "$PORT" >"$LOGS/api.log" 2>&1 &
pids+=($!)
# Until either stops (or Playwright stops this script).
wait -n
