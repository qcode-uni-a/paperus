#!/usr/bin/env bash
# The library on this computer, end to end (local.mjs): the app (a debug
# build) with a bundle (app/local/build.sh's folder) instead of the
# release's download, tauri-driver and WebKitWebDriver on a display of
# their own. The app's settings and data in a temporary folder; afterwards
# no process of the library is left. Usage: local.sh <bundle folder>
set -euo pipefail
if [ -z "${PAPERUS_APP_TESTS_BUS:-}" ] && command -v dbus-run-session >/dev/null; then
  PAPERUS_APP_TESTS_BUS=1 exec dbus-run-session -- bash "$0" "$@"
fi
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
APP=$ROOT/app/src-tauri/target/debug/paperus-app
export PAPERUS_LOCAL_BUNDLE=$(cd "$1" && pwd)
STATE=$(mktemp -d -t paperus-app-local.XXXXXX)

pids=()
cleanup() {
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  # The database the app leaves running when killed.
  "$PAPERUS_LOCAL_BUNDLE/postgres/bin/pg_ctl" -D "$STATE"/data/*/library/database -m fast stop >/dev/null 2>&1 || true
  wait 2>/dev/null || true
  rm -rf "$STATE"
}
trap cleanup EXIT

[ -x "$APP" ] || { echo "build the app first: cargo build (in app/src-tauri)" >&2; exit 1; }
mkdir -p "$STATE/config" "$STATE/data"
export XDG_CONFIG_HOME=$STATE/config XDG_DATA_HOME=$STATE/data WEBKIT_DISABLE_COMPOSITING_MODE=1
if command -v Xvfb >/dev/null; then
  Xvfb :98 -screen 0 1280x900x24 >/dev/null 2>&1 &
  export DISPLAY=:98 GDK_BACKEND=x11
else
  broadwayd :8 >/dev/null 2>&1 &
  export GDK_BACKEND=broadway BROADWAY_DISPLAY=:8
fi
pids+=($!)
sleep 1
tauri-driver --native-driver "$(command -v WebKitWebDriver)" >"$STATE/driver.log" 2>&1 &
pids+=($!)
for _ in $(seq 30); do curl -sf http://127.0.0.1:4444/status >/dev/null && break; sleep 1; done

node "$ROOT/app/tests/local.mjs" "$APP" || {
  tail -n 40 "$STATE/driver.log" "$STATE"/data/*/library/*.log >&2
  exit 1
}
# The server and worker end with the app (--stop-with-stdin).
sleep 3
if pgrep -f "paperus (serve|worker) .*--stop-with-stdin" >/dev/null; then
  echo "the library's server or worker outlived the app" >&2
  exit 1
fi
echo "no server or worker left after the app"
