#!/usr/bin/env bash
# Starts a library on this computer from build.sh's folder as the app does
# (src-tauri/src/local.rs), once: a new database with a password, the
# schema, the only user, the server; then checks that it answers, logs in,
# serves the website and has pgvector. Usage: smoke.sh <folder>
set -euo pipefail
BUNDLE=$(cd "$1" && pwd)
DATA=$(mktemp -d)
PG=$BUNDLE/postgres/bin
if [ -x "$BUNDLE/python/bin/python3" ]; then PY=$BUNDLE/python/bin/python3; else PY=$BUNDLE/python/python.exe; fi
DB_PORT=54329
PORT=8765
PASSWORD=smoke-test-password-$RANDOM$RANDOM

server=
cleanup() {
  [ -n "$server" ] && kill "$server" 2>/dev/null || true
  "$PG/pg_ctl" -D "$DATA/db" -m fast stop >/dev/null 2>&1 || true
  rm -rf "$DATA"
}
trap cleanup EXIT

printf '%s\n' "$PASSWORD" > "$DATA/db-password"
"$PG/initdb" -D "$DATA/db" -U paperus -E UTF8 --auth=scram-sha-256 --pwfile="$DATA/db-password" >/dev/null
"$PG/pg_ctl" -D "$DATA/db" -l "$DATA/postgres.log" -w \
  -o "-p $DB_PORT -c listen_addresses=127.0.0.1 -c unix_socket_directories=" start >/dev/null
PGPASSWORD=$PASSWORD "$PG/createdb" -h 127.0.0.1 -p "$DB_PORT" -U paperus paperus

export PAPERUS_DATABASE_URL="postgresql+psycopg://paperus:$PASSWORD@127.0.0.1:$DB_PORT/paperus"
export PAPERUS_STORAGE_PATH=$DATA/files PAPERUS_BACKUP_PATH=$DATA/backups PAPERUS_COPY_PATH=$DATA/copy
export PAPERUS_WEB_PATH=$BUNDLE/web PAPERUS_COOKIE_SECURE=false PAPERUS_ML_URLS='["http://127.0.0.1:9"]'
"$PY" -m paperus migrate
printf '%s\n' "$PASSWORD" | "$PY" -m paperus user create me --admin --password-stdin
"$PY" -m paperus serve --host 127.0.0.1 --port "$PORT" > "$DATA/server.log" 2>&1 &
server=$!

for _ in $(seq 60); do
  curl -fs "http://127.0.0.1:$PORT/api/health" >/dev/null && break
  sleep 1
done
curl -fs "http://127.0.0.1:$PORT/api/health" || { cat "$DATA/server.log"; exit 1; }
echo
curl -fs -o /dev/null -c "$DATA/cookies" -H 'Content-Type: application/json' \
  -d "{\"username\": \"me\", \"password\": \"$PASSWORD\"}" "http://127.0.0.1:$PORT/api/auth/login"
curl -fs -b "$DATA/cookies" "http://127.0.0.1:$PORT/api/auth/me" | grep -q '"username":"me"'
curl -fs "http://127.0.0.1:$PORT/" | grep -q '<html'
PGPASSWORD=$PASSWORD "$PG/psql" -h 127.0.0.1 -p "$DB_PORT" -U paperus -d paperus -tAc \
  "SELECT extversion FROM pg_extension WHERE extname = 'vector'" | grep -q .
echo "smoke test passed: server, login, website, pgvector"
