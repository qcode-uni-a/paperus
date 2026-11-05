#!/bin/sh
# Started as root, hand the model cache to the paperus user (Docker creates
# missing bind-mounted folders as root), then drop privileges.
set -e

if [ "$(id -u)" = 0 ]; then
    if [ "$(stat -c %U "$PAPERUS_ML_CACHE_PATH")" != paperus ]; then
        chown -R paperus:paperus "$PAPERUS_ML_CACHE_PATH"
    fi
    HOME=/home/paperus exec setpriv --reuid=paperus --regid=paperus --init-groups "$0" "$@"
fi

exec "$@"
