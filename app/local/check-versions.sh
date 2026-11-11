#!/usr/bin/env bash
# The library on this computer runs the same PostgreSQL and Python major
# versions as a server installation (compose.yaml, the Dockerfile) and CI:
# one tested combination, and libraries move between the two. Minor
# versions may differ (fixes). Run by pre-commit and so by CI.
set -euo pipefail
cd "$(dirname "$0")/../.."
fail=0
same() {
  if [ "$2" != "$3" ]; then
    echo "$1: the library on this computer has $3, the server $2 (app/local/build.sh)" >&2
    fail=1
  fi
}
bundle_pg=$(grep -oE '^POSTGRES=[0-9]+' app/local/build.sh | cut -d= -f2)
bundle_py=$(grep -oE '^PYTHON=[0-9]+\.[0-9]+' app/local/build.sh | cut -d= -f2)
for file in compose.yaml deploy/compose.yaml .github/workflows/ci.yml; do
  for pg in $(grep -oE 'pgvector/pgvector:pg[0-9]+' "$file" | grep -oE '[0-9]+$' | sort -u); do
    same "PostgreSQL in $file" "$pg" "$bundle_pg"
  done
done
for file in Dockerfile ml/Dockerfile; do
  # Each version once (a Dockerfile may have several stages on Python).
  for py in $(grep -oE '^FROM python:[0-9]+\.[0-9]+' "$file" | grep -oE '[0-9]+\.[0-9]+$' | sort -u); do
    same "Python in $file" "$py" "$bundle_py"
  done
done
exit $fail
