#!/usr/bin/env bash
# The app's journeys (journeys.mjs): the e2e tests' paperus (a fresh
# database paperus_e2e; needs web/build and Postgres, see e2e/README.md),
# the app (a debug build), tauri-driver and WebKitWebDriver, on a display
# of their own (Xvfb, else GTK's Broadway). The app's settings, data
# and the browser it opens are stand-ins in a temporary folder.
set -euo pipefail
# A session bus of its own (the app's single-instance check uses it).
if [ -z "${PAPERUS_APP_TESTS_BUS:-}" ] && command -v dbus-run-session >/dev/null; then
  PAPERUS_APP_TESTS_BUS=1 exec dbus-run-session -- bash "$0" "$@"
fi
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
APP=$ROOT/app/src-tauri/target/debug/paperus-app
export PAPERUS_E2E_PORT=${PAPERUS_E2E_PORT:-8100}
LIBRARY=http://127.0.0.1:$PAPERUS_E2E_PORT
STATE=$(mktemp -d -t paperus-app-tests.XXXXXX)

pids=()
cleanup() {
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  rm -rf "$STATE"
}
trap cleanup EXIT

[ -x "$APP" ] || { echo "build the app first: cargo build (in app/src-tauri)" >&2; exit 1; }

PAPERUS_E2E_LOGS=$STATE/server-logs setsid bash "$ROOT/e2e/scripts/serve.sh" >"$STATE/serve.log" 2>&1 &
pids+=($!)
# The journeys stop it to go offline (its process group).
export PAPERUS_APP_TESTS_SERVER=$!
for _ in $(seq 180); do curl -sf "$LIBRARY/api/health" >/dev/null && break; sleep 1; done
curl -sf -X POST "$LIBRARY/api/setup/admin" -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"e2e-admin-password"}' >/dev/null

# The system's browser: writes down what it was asked to open.
mkdir -p "$STATE/bin" "$STATE/config" "$STATE/data"
printf '#!/bin/sh\necho "$1" >> %s/opened.txt\n' "$STATE" >"$STATE/bin/xdg-open"
chmod +x "$STATE/bin/xdg-open"
export PATH=$STATE/bin:$PATH XDG_CONFIG_HOME=$STATE/config XDG_DATA_HOME=$STATE/data
export WEBKIT_DISABLE_COMPOSITING_MODE=1
# A PDF to open with the app.
printf '%%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%%%EOF\n' >"$STATE/opened-with.pdf"

driver=(tauri-driver --native-driver "$(command -v WebKitWebDriver)")
# One display for all (the app started a second time too).
if command -v Xvfb >/dev/null; then
  Xvfb :97 -screen 0 1280x900x24 >/dev/null 2>&1 &
  export DISPLAY=:97 GDK_BACKEND=x11
else
  broadwayd :7 >/dev/null 2>&1 &
  export GDK_BACKEND=broadway BROADWAY_DISPLAY=:7
fi
pids+=($!)
sleep 1
"${driver[@]}" >"$STATE/driver.log" 2>&1 &
pids+=($!)
for _ in $(seq 30); do curl -sf http://127.0.0.1:4444/status >/dev/null && break; sleep 1; done

node "$ROOT/app/tests/journeys.mjs" "$APP" "$STATE/opened.txt" "$STATE/opened-with.pdf" \
  "$STATE/data/io.github.qcode-uni-a.paperus" ||
  { tail -n 30 "$STATE/driver.log" "$STATE/server-logs/"*.log >&2; exit 1; }
