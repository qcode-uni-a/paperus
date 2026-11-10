#!/usr/bin/env bash
# The homepage's screenshots (site/screenshots/) of the demo library, from
# a fresh paperus (the e2e tests' server).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PDFS=$(mktemp -d -t paperus-demo.XXXXXX)
trap 'rm -rf "$PDFS"' EXIT
bash "$ROOT/e2e/demo/pdfs.sh" "$PDFS"
npm --prefix "$ROOT/web" run build
cd "$ROOT/e2e"
PAPERUS_DEMO_PDFS=$PDFS npx playwright test -c screenshots.config.ts
