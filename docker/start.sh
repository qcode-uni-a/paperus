#!/bin/sh
# Container entry point: "serve" (the default) migrates the database first,
# "worker" runs background jobs, anything else runs as given (e.g.
# "paperus backup list"). Started as root, it hands the data folders to the paperus
# user (Docker creates missing bind-mounted folders as root) and drops
# privileges; started as another user, it just runs.
set -e

if [ "$(id -u)" = 0 ]; then
    for folder in "$PAPERUS_STORAGE_PATH" "$PAPERUS_BACKUP_PATH" "$PAPERUS_COPY_PATH"; do
        mkdir -p "$folder"
        if [ "$(stat -c %U "$folder")" != paperus ]; then
            # A network share may refuse (root squashed): said, not fatal.
            chown -R paperus:paperus "$folder" 2>/dev/null \
                || echo "start: $folder could not be given to the paperus user; give it to uid 1000 where it is" >&2
        fi
    done
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
