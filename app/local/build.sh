#!/usr/bin/env bash
# The library on this computer (docs/apps.md, app/README.md): everything a
# paperus for one person needs, without installing anything, for one
# platform (a Rust target, e.g. x86_64-unknown-linux-gnu) into a folder:
#
#   python/    a standalone Python (python-build-standalone) with the server
#              and its locked dependencies (server/uv.lock)
#   postgres/  PostgreSQL (theseus-rs/postgresql-binaries) with pgvector,
#              built against it here
#   web/       the website, built
#   VERSION    paperus' version
#
# Every download is pinned to its SHA-256. Run in CI (.github/workflows/
# local.yml); on Windows in Git Bash with MSVC's tools on the PATH.
# Usage: build.sh <target> <folder>
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
TARGET=$1
OUT=$(mkdir -p "$2" && cd "$2" && pwd)

PYTHON=3.13.18+20261026
POSTGRES=18.6.1
PGVECTOR=0.8.7
PGVECTOR_SHA256=cac0b10c360f05b2d521200105ba3697e773d4cd3731f5a915a7e37ebe0bea85
case $TARGET in
  x86_64-unknown-linux-gnu)
    PYTHON_SHA256=df15fe60d3ff55bf9dcf25824b5572756bb8816ff93865a273d3301d7066a8b7
    POSTGRES_SHA256=e84b02dd8d0ce5879fb697330a789231c8b8f8d958dae3ad4d90fecc710b1315 ;;
  aarch64-apple-darwin)
    PYTHON_SHA256=8392b6ea51d94391befb2c31ebe75463f045d0b69dfcf5e1bb3234e1f5fa3405
    POSTGRES_SHA256=89e91cc80650a43d22c018b95ca356a0c9e15838a1182fed2880bfb5d7d9c9a6 ;;
  x86_64-apple-darwin)
    PYTHON_SHA256=7412c19d896c99431b74a18a5643e110449a7f9590fbab179c3e5ab27b9aa9e3
    POSTGRES_SHA256=4229812543e19c91864ebdf5d8f78883c5816d51d4cc5d065298260c1f64d37e ;;
  x86_64-pc-windows-msvc)
    PYTHON_SHA256=7369f7a35f261222a6ac8b3a87c1c88eeebee8af945d85346202591a64038dd3
    POSTGRES_SHA256=0c0c845626ed77c605d716051c9e8df3368d07fbbd9f61ea39a4c5c0536fde7e ;;
  *) echo "unknown target $TARGET" >&2; exit 1 ;;
esac

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

sha256() {
  if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1
}

# A download, checked against its pinned SHA-256.
fetch() {
  local url=$1 file=$2 expected=$3
  curl -fsSL --retry 3 -o "$file" "$url"
  local got
  got=$(sha256 "$file")
  if [ "$got" != "$expected" ]; then
    echo "$url: SHA-256 $got, not $expected" >&2
    exit 1
  fi
}

rm -rf "$OUT"/python "$OUT"/postgres "$OUT"/web

# Python, with the server and its locked dependencies.
fetch "https://github.com/astral-sh/python-build-standalone/releases/download/${PYTHON#*+}/cpython-$PYTHON-$TARGET-install_only_stripped.tar.gz" \
  "$WORK/python.tar.gz" "$PYTHON_SHA256"
tar xzf "$WORK/python.tar.gz" -C "$OUT"
if [ -x "$OUT/python/bin/python3" ]; then PY=$OUT/python/bin/python3; else PY=$OUT/python/python.exe; fi
uv export --project "$ROOT/server" --frozen --no-dev --no-emit-project --no-hashes -o "$WORK/requirements.txt" >/dev/null
uv build --project "$ROOT/server" --wheel -o "$WORK/dist" >/dev/null
uv pip install --python "$PY" --no-cache -r "$WORK/requirements.txt"
uv pip install --python "$PY" --no-cache --no-deps "$WORK"/dist/paperus-*.whl

# PostgreSQL, and pgvector built against it (no CPU-specific flags: it
# runs on any computer of the platform).
fetch "https://github.com/theseus-rs/postgresql-binaries/releases/download/$POSTGRES/postgresql-$POSTGRES-$TARGET.tar.gz" \
  "$WORK/postgres.tar.gz" "$POSTGRES_SHA256"
mkdir -p "$OUT/postgres"
tar xzf "$WORK/postgres.tar.gz" -C "$OUT/postgres" --strip-components=1
fetch "https://github.com/pgvector/pgvector/archive/refs/tags/v$PGVECTOR.tar.gz" \
  "$WORK/pgvector.tar.gz" "$PGVECTOR_SHA256"
tar xzf "$WORK/pgvector.tar.gz" -C "$WORK"
if [ "$TARGET" = x86_64-pc-windows-msvc ]; then
  (cd "$WORK/pgvector-$PGVECTOR" && PGROOT=$(cygpath -w "$OUT/postgres") nmake //NOLOGO //F Makefile.win \
    && PGROOT=$(cygpath -w "$OUT/postgres") nmake //NOLOGO //F Makefile.win install)
else
  make -C "$WORK/pgvector-$PGVECTOR" PG_CONFIG="$OUT/postgres/bin/pg_config" OPTFLAGS="" >/dev/null
  make -C "$WORK/pgvector-$PGVECTOR" PG_CONFIG="$OUT/postgres/bin/pg_config" OPTFLAGS="" install >/dev/null
fi
# What only building needs.
rm -rf "$OUT/postgres/include" "$OUT/postgres/lib/pgxs" "$OUT/postgres/doc" "$OUT/postgres/share/doc"
find "$OUT/postgres/lib" -name '*.a' -delete

# The website.
npm --prefix "$ROOT/web" ci --no-audit --no-fund >/dev/null
npm --prefix "$ROOT/web" run build >/dev/null
cp -R "$ROOT/web/build" "$OUT/web"

sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/server/pyproject.toml" > "$OUT/VERSION"
du -sh "$OUT"/python "$OUT"/postgres "$OUT"/web
