#!/usr/bin/env bash
# Makes the demo (e2e/demo/README.md) in the homepage's folder: the website
# built for it into site/demo/, its service worker, and the recording of a
# fresh paperus with the demo library (the e2e tests' server, port 8100).
# PAPERUS_DEMO_BASE: where it is served (GitHub Pages: /paperus/demo).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
BASE=${PAPERUS_DEMO_BASE:-/paperus/demo}
SITE=${PAPERUS_DEMO_SITE:-$ROOT/site}
PDFS=$(mktemp -d -t paperus-demo.XXXXXX)
trap 'rm -rf "$PDFS"' EXIT
# The public-domain scans: downloaded once, kept there (CI caches the folder).
PAPERS=${PAPERUS_DEMO_PAPERS:-$ROOT/e2e/demo/papers}
PAPERS=$(mkdir -p "$PAPERS" && cd "$PAPERS" && pwd)

bash "$ROOT/e2e/demo/pdfs.sh" "$PDFS"
node "$ROOT/e2e/demo/fetch.ts" "$PAPERS"
uv --directory "$ROOT/server" run python "$ROOT/e2e/demo/words.py" "$PDFS/words.json" "$PAPERS"/*.pdf
# The website the recording's server serves, and the demo's own.
npm --prefix "$ROOT/web" run build
rm -rf "$SITE/demo"
PAPERUS_WEB_BASE=$BASE PAPERUS_WEB_OUT=$SITE/demo VITE_PAPERUS_DEMO=1 npm --prefix "$ROOT/web" run build
cp "$ROOT/web/demo/service-worker.js" "$SITE/demo/demo-service-worker.js"
# The demo's start, and GitHub Pages' answer to unknown paths: the demo's
# pages, opened directly, start the website there.
cp "$SITE/demo/200.html" "$SITE/demo/index.html"
cp "$SITE/demo/200.html" "$SITE/404.html"
cd "$ROOT/e2e"
PAPERUS_DEMO_PDFS=$PDFS PAPERUS_DEMO_PAPERS=$PAPERS PAPERUS_DEMO_WORDS=$PDFS/words.json \
  PAPERUS_DEMO_OUT=$SITE/demo/recording npx playwright test -c demo.config.ts
du -sh "$SITE/demo/recording"
