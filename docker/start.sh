#!/bin/sh
# Container entry point: "serve" (the default) migrates the database first,
# "worker" runs background jobs. Started as root, it hands the data folder to
# the paperus user (Docker creates missing bind-mounted folders as root) and
# drops privileges; started as another user, it just runs.
set -e

if [ "$(id -u)" = 0 ]; then
    if [ "$(stat -c %U "$PAPERUS_STORAGE_PATH")" != paperus ]; then
        chown -R paperus:paperus "$PAPERUS_STORAGE_PATH"
    fi
    HOME=/home/paperus exec setpriv --reuid=paperus --regid=paperus --init-groups "$0" "$@"
fi

case "$1" in
    serve)
        paperus migrate
        exec paperus serve --host 0.0.0.0 --port 8000
        ;;
    worker)
        exec paperus worker
        ;;
    *)
        exec "$@"
        ;;
esac
