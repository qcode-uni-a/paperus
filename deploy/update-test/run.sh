#!/usr/bin/env bash
# The update test: an installation from compose.yaml on the last release,
# with a small library in it (library.py fill), updated as the
# documentation says (a newer image, "docker compose up -d") to the version
# under test; then everything must still be there (library.py check).
#
#   deploy/update-test/run.sh [TO] [FROM]
#
# TO: the image tag under test (default "ci", e.g. from
#   docker build -t ghcr.io/qcode-uni-a/paperus-server:ci .);
# FROM: the tag updated from (default "release", the last release).
# Without the ML service: search by words only.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
TO=${1:-ci}
FROM=${2:-release}
PORT=${PAPERUS_UPDATE_TEST_PORT:-8200}
URL=http://127.0.0.1:$PORT
WORK=$(mktemp -d -t paperus-update-test.XXXXXX)

cp "$HERE/../compose.yaml" "$WORK/"
cat >"$WORK/.env" <<EOF
UPLOAD_LOCATION=./library
DB_DATA_LOCATION=./postgres
BACKUP_LOCATION=./backups
COPY_LOCATION=./library-copy
MODEL_CACHE_LOCATION=./model-cache
PAPERUS_VERSION=$FROM
PAPERUS_PORT=$PORT
DB_USERNAME=paperus
DB_PASSWORD=update-test
DB_DATABASE_NAME=paperus
ML_TOKEN=update-test
ML_URLS=["http://127.0.0.1:9"]
# 0.0.18 could not set up its first administrator without one.
CONTACT_EMAIL=update-test@example.org
COOKIE_SECURE=false
EOF
compose() { docker compose --project-directory "$WORK" -p paperus-update-test "$@"; }

cleanup() {
  status=$?
  if [ "$status" != 0 ]; then compose logs server worker | tail -n 200; fi
  compose down --volumes >/dev/null 2>&1 || true
  # The database's and the server's folders belong to their containers' users.
  docker run --rm -v "$WORK:/work" pgvector/pgvector:pg18 \
    sh -c 'rm -rf /work/postgres /work/library /work/backups /work/library-copy' || true
  rm -rf "$WORK"
}
trap cleanup EXIT

started() {
  for _ in $(seq 120); do
    if curl -fsS "$URL/api/health/db" >/dev/null 2>&1; then return; fi
    sleep 1
  done
  echo "paperus did not start on $URL" >&2
  return 1
}

echo "== paperus-server:$FROM with a small library"
compose pull --quiet db server
compose up -d db server worker
started
uv run --quiet "$HERE/library.py" fill "$URL" "$WORK/library.json"

echo "== updated to paperus-server:$TO"
sed -i "s/^PAPERUS_VERSION=.*/PAPERUS_VERSION=$TO/" "$WORK/.env"
compose up -d db server worker
started
uv run --quiet "$HERE/library.py" check "$URL" "$WORK/library.json"
