#!/usr/bin/env bash
# The app's journeys (journeys.mjs) on Windows (#45): the e2e tests'
# paperus started from build.sh's Windows folder (PostgreSQL with pgvector,
# Python with the server, the website), the app (a debug build), and
# tauri-driver with Edge's WebDriver for WebView2. The app's data goes to
# the runner's own AppData. Run by app-tests.yml.
# Usage: windows.sh <bundle folder> <msedgedriver.exe>
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
BUNDLE=$(cd "$1" && pwd)
DRIVER=$2
APP=$ROOT/app/src-tauri/target/debug/paperus-app.exe
STATE=$(mktemp -d)
PG=$BUNDLE/postgres/bin
PY=$BUNDLE/python/python.exe
DB_PORT=54329
export PAPERUS_E2E_PORT=8100
LIBRARY=http://127.0.0.1:$PAPERUS_E2E_PORT
PASSWORD=journeys-$RANDOM$RANDOM

pids=()
cleanup() {
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  "$PG/pg_ctl" -D "$STATE/db" -m fast stop >/dev/null 2>&1 || true
}
trap cleanup EXIT

printf '%s\n' "$PASSWORD" > "$STATE/db-password"
"$PG/initdb" -D "$STATE/db" -U paperus -E UTF8 --auth=scram-sha-256 --pwfile="$STATE/db-password" >/dev/null
"$PG/pg_ctl" -D "$STATE/db" -l "$STATE/postgres.log" -w \
  -o "-p $DB_PORT -c listen_addresses=127.0.0.1" start >/dev/null
PGPASSWORD=$PASSWORD "$PG/createdb" -h 127.0.0.1 -p "$DB_PORT" -U paperus paperus

export PAPERUS_DATABASE_URL="postgresql+psycopg://paperus:$PASSWORD@127.0.0.1:$DB_PORT/paperus"
export PAPERUS_STORAGE_PATH=$STATE/files PAPERUS_BACKUP_PATH=$STATE/backups PAPERUS_COPY_PATH=$STATE/copy
export PAPERUS_WEB_PATH=$BUNDLE/web PAPERUS_COOKIE_SECURE=false PAPERUS_ML_URLS='["http://127.0.0.1:9"]'
"$PY" -m paperus migrate
"$PY" -m paperus worker >"$STATE/worker.log" 2>&1 &
pids+=($!)
"$PY" -m paperus serve --host 127.0.0.1 --port "$PAPERUS_E2E_PORT" >"$STATE/server.log" 2>&1 &
pids+=($!)
for _ in $(seq 90); do curl -sf "$LIBRARY/api/health" >/dev/null && break; sleep 1; done
curl -sf -X POST "$LIBRARY/api/setup/admin" -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"e2e-admin-password"}' >/dev/null

# A PDF to open with the app.
printf '%%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%%%EOF\n' >"$STATE/opened-with.pdf"

tauri-driver --native-driver "$DRIVER" >"$STATE/driver.log" 2>&1 &
pids+=($!)
for _ in $(seq 30); do curl -sf http://127.0.0.1:4444/status >/dev/null && break; sleep 1; done

PAPERUS_APP_TESTS_SYSTEM=windows node "$ROOT/app/tests/journeys.mjs" "$APP" "$STATE/opened.txt" \
  "$(cygpath -w "$STATE/opened-with.pdf")" "$APPDATA/io.github.qcode-uni-a.paperus" ||
  { tail -n 30 "$STATE/server.log" >&2
    grep -E "offline:|login to|panicked" "$STATE/driver.log" >&2 || tail -n 30 "$STATE/driver.log" >&2
    exit 1; }
