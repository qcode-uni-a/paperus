#!/usr/bin/env bash
# The homepage's screenshots (site/screenshots/) of the demo library, from
# a fresh paperus (the e2e tests' server).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PDFS=$(mktemp -d -t paperus-demo.XXXXXX)
trap 'rm -rf "$PDFS"' EXIT
PAPERS=${PAPERUS_DEMO_PAPERS:-$ROOT/e2e/demo/papers}
PAPERS=$(mkdir -p "$PAPERS" && cd "$PAPERS" && pwd)
bash "$ROOT/e2e/demo/pdfs.sh" "$PDFS"
node "$ROOT/e2e/demo/fetch.ts" "$PAPERS"
npm --prefix "$ROOT/web" run build
cd "$ROOT/e2e"
PAPERUS_DEMO_PDFS=$PDFS PAPERUS_DEMO_PAPERS=$PAPERS npx playwright test -c screenshots.config.ts
