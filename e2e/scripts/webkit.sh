#!/usr/bin/env bash
# The tests in WebKit on a computer where Playwright's WebKit doesn't run
# (it is built for Ubuntu and Debian): the browser in Playwright's own
# container, the tests and paperus here. Arguments go to `playwright test`.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(npx playwright --version | awk '{print $2}')
PORT=${PAPERUS_E2E_BROWSER_PORT:-3456}
NAME=paperus-e2e-webkit

docker run -d --name "$NAME" --rm --init --network host --ipc host \
  "mcr.microsoft.com/playwright:v$VERSION-noble" \
  npx -y "playwright@$VERSION" run-server --port "$PORT" --host 127.0.0.1 >/dev/null
trap 'docker stop "$NAME" >/dev/null' EXIT
until docker logs "$NAME" 2>&1 | grep -q Listening; do sleep 1; done

PAPERUS_E2E_BROWSER=webkit PW_TEST_CONNECT_WS_ENDPOINT="ws://127.0.0.1:$PORT/" \
  npx playwright test "$@"
