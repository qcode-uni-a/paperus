#!/usr/bin/env bash
# Whether the browser extension built from this commit differs from the one
# built from the previous release tag (or the tag given), apart from its
# version number. Writes changed=true|false to $GITHUB_OUTPUT (or prints
# it); needs the full history.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
previous=${1:-$(git describe --tags --abbrev=0 --match 'v*' HEAD^ 2>/dev/null || true)}
result() {
	echo "$1"
	echo "changed=$2" >>"${GITHUB_OUTPUT:-/dev/null}"
	exit 0
}
[ -n "$previous" ] || result "No earlier release: publish." true

compare=$(mktemp -d)
build() { # folder, name → $compare/name: what ships, without the version
	(cd "$1/extension" && npm ci --silent && npm run -s build >/dev/null)
	mkdir "$compare/$2"
	cp -r "$1"/extension/dist/chrome "$1"/extension/dist/firefox "$compare/$2"
	for manifest in "$compare/$2"/*/manifest.json; do
		node -e 'const f = process.argv[1], m = JSON.parse(require("fs").readFileSync(f));
			delete m.version; require("fs").writeFileSync(f, JSON.stringify(m, null, 1));' "$manifest"
	done
}
old=$(mktemp -d)
git worktree add -q --detach "$old" "$previous"
trap 'git worktree remove --force "$old"' EXIT
build "$old" before
build "$root" now
if diff -r "$compare/before" "$compare/now" >/dev/null; then
	result "The extension is the same as in $previous: not published." false
fi
diff -r "$compare/before" "$compare/now" | head -40 || true
result "The extension changed since $previous: publish." true
