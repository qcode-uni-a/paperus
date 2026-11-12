#!/usr/bin/env bash
# A release's mechanical part (the rest: .claude/skills/release/SKILL.md).
#
#   scripts/release.sh 0.0.30          every version number set to 0.0.30
#   scripts/release.sh --check 0.0.30  all set, and the changelog ready
#
# Setting them needs main as it is on GitHub, with nothing changed here and
# CI green on its last commit (RELEASE_SKIP_CHECKS=1 skips that, to try the
# script out). Each file is changed by its own tool, not by line numbers:
# npm for the package files, uv for the Python locks, cargo for the app's.
# What the Release workflow compares with the tag ("Tag matches the package
# versions") is checked here first, and the lock files and README too.
set -euo pipefail
cd "$(dirname "$0")/.."

die() { echo "release: $*" >&2; exit 1; }

check=false
if [ "${1:-}" = "--check" ]; then
  check=true
  shift
fi
new=${1:-}
[[ $new =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "usage: scripts/release.sh [--check] 0.0.30"

PYTHON=(server ml)
NODE=(web client extension)
APP=app/src-tauri

current() { grep -m1 '^version = ' server/pyproject.toml | cut -d'"' -f2; }

# Every place the version is written, as "file: version found".
versions() {
  for dir in "${PYTHON[@]}"; do
    echo "$dir/pyproject.toml: $(grep -m1 '^version = ' "$dir/pyproject.toml" | cut -d'"' -f2)"
    local name
    name=$(grep -m1 '^name = ' "$dir/pyproject.toml" | cut -d'"' -f2)
    echo "$dir/uv.lock: $(awk -v name="$name" '
      $0 == "name = \"" name "\"" { found = 1; next }
      found && /^version = / { gsub(/"/, "", $3); print $3; exit }' "$dir/uv.lock")"
  done
  for dir in "${NODE[@]}"; do
    echo "$dir/package.json: $(node -p "require('./$dir/package.json').version")"
    echo "$dir/package-lock.json: $(node -p "
      const lock = require('./$dir/package-lock.json');
      lock.version === lock.packages[''].version ? lock.version : 'differs inside'")"
  done
  echo "$APP/Cargo.toml: $(grep -m1 '^version = ' "$APP/Cargo.toml" | cut -d'"' -f2)"
  echo "$APP/Cargo.lock: $(awk '
    $0 == "name = \"paperus-app\"" { found = 1; next }
    found && /^version = / { gsub(/"/, "", $3); print $3; exit }' "$APP/Cargo.lock")"
  echo "README.md: $(sed -n 's/.*Status: beta (\([0-9.]*\)).*/\1/p' README.md)"
}

verify() {
  local wrong
  wrong=$(versions | grep -v ": $new$" || true)
  [ -z "$wrong" ] || die "not $new yet:"$'\n'"$wrong"
}

if $check; then
  verify
  heading=$(grep -n -m1 '^## ' CHANGELOG.md)
  [[ $heading == *"## $new ("*")" ]] || die "CHANGELOG.md starts with \"${heading#*:}\", not \"## $new (date)\""
  line=${heading%%:*}
  headline=$(sed -n "$((line + 2))p" CHANGELOG.md)
  [[ $headline =~ ^\*[^*].*\*$ ]] || die "CHANGELOG.md: no headline (*…*) under ## $new"
  ! grep -q '^## Unreleased' CHANGELOG.md || die "CHANGELOG.md still has an Unreleased section"
  notes=$(node -p "require('./extension/amo-metadata.json').version.approval_notes.length")
  [ "$notes" -le 2900 ] || die "extension/amo-metadata.json: approval_notes has $notes characters, at most 2900"
  echo "release: $new ready (versions, changelog, Mozilla's notes: $notes characters)"
  exit 0
fi

old=$(current)
[ "$old" != "$new" ] || die "already $new"
! git rev-parse -q --verify "refs/tags/v$new" >/dev/null || die "tag v$new exists"

if [ "${RELEASE_SKIP_CHECKS:-}" != 1 ]; then
  [ "$(git branch --show-current)" = main ] || die "not on main"
  [ -z "$(git status --porcelain)" ] || die "uncommitted changes"
  git fetch -q origin main
  [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] ||
    die "main differs from GitHub's: git pull --rebase (others may have pushed), then again"
  ci=$(gh run list --commit "$(git rev-parse HEAD)" --workflow CI --json status,conclusion \
    --jq '.[0] | "\(.status) \(.conclusion)"')
  [ "$ci" = "completed success" ] || die "CI on $(git rev-parse --short HEAD): ${ci:-not run} (wait for it, or fix it first)"
fi

echo "release: $old → $new"
for dir in "${PYTHON[@]}"; do
  sed -i "0,/^version = \"$old\"/s//version = \"$new\"/" "$dir/pyproject.toml"
  (cd "$dir" && uv lock -q)
done
for dir in "${NODE[@]}"; do
  (cd "$dir" && npm version "$new" --no-git-tag-version --allow-same-version >/dev/null)
done
sed -i "0,/^version = \"$old\"/s//version = \"$new\"/" "$APP/Cargo.toml"
cargo update -q --workspace --offline --manifest-path "$APP/Cargo.toml"
sed -i "s/Status: beta ($old)/Status: beta ($new)/" README.md

verify
git diff --stat
echo "release: next, CHANGELOG.md (## $new ($(date +%F)) with a headline), then scripts/release.sh --check $new"
