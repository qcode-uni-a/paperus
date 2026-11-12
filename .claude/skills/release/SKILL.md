---
name: release
description: Release a new paperus version (0.0.N) - check it is ready, set the versions, write the changelog, tag, and watch the Release workflow publish it. Use when asked to release, publish or tag a version.
---

# Releasing paperus

A tag `vX.Y.Z` on main starts the Release workflow (`.github/workflows/release.yml`):
it tests again, checks the tag against the package versions, then publishes the
container images, PyPI and npm packages, the Firefox add-on (and Chrome's, once
switched on), the app and the GitHub release with the changelog's notes. What
publishes is switched on by repository variables (`PUBLISH_*`, see
`docs/operations.md`, "Releases").

**Only on the maintainer's go.** Propose a release, say what goes in, and wait.
Pushing the tag publishes everything and cannot be taken back; a pushed tag is
never moved or deleted without the maintainer saying so.

Other sessions and people push to main too: pull before every push, and check
that a new migration's number is not taken meanwhile.

## 1. Ready?

```bash
git pull --rebase
git log --oneline "$(git describe --tags --abbrev=0)"..HEAD   # what goes in
gh run list --commit "$(git rev-parse HEAD)" --workflow CI     # green?
```

- CI must be green on main's last commit. A failed job: read its log
  (`gh run view <id> --log-failed`); fix a real failure first; an end-to-end
  test that fails now and then (WebKit, mostly) is still a bug in the test or
  the app, worth a look, but may be re-run (`gh run rerun <id> --failed`).
- Tell the maintainer what the release brings (the changelog's "Unreleased"
  section and the commits since the last tag), and what to know: a database
  migration (runs by itself on update; CI's "Update from the last release" job
  tries it on the last release), new permissions for the browser extension,
  anything not tried in a real browser (Firefox) or on real data.

## 2. The versions

```bash
scripts/release.sh 0.0.30
```

It refuses unless main is GitHub's, unchanged, with CI green; then sets every
version (Python and its `uv.lock`s, the npm packages and their locks, the app
and its `Cargo.lock`, the README's status line) and checks them.

## 3. The changelog

In `CHANGELOG.md`, "## Unreleased" becomes `## 0.0.30 (YYYY-MM-DD)`, with a
headline under it: one funny line in italics about this release (e.g.
`*Your papers can now line up by author, year, journal or title, which is more
than can be said for your desk.*`). Every release has one.

Changes on main the section does not list yet get an entry, in its style: a
bold lead saying what changed for the person using paperus, then plainly what
it does and why (before: …; now: …), the most noticeable first. Neutral words
("OIDC login", not a particular kind of organisation's); no other projects
named as inspiration.

If the browser extension's permissions or behaviour changed, its notes for
Mozilla's reviewers (`extension/amo-metadata.json`, `approval_notes`, at most
2,900 characters: AMO refuses longer ones) and `extension/PRIVACY.md` say so.

```bash
scripts/release.sh --check 0.0.30
```

## 4. Commit, tag, push

```bash
git add -A CHANGELOG.md README.md */package.json */package-lock.json \
  server/pyproject.toml server/uv.lock ml/pyproject.toml ml/uv.lock \
  app/src-tauri/Cargo.toml app/src-tauri/Cargo.lock
git commit -m "Release 0.0.30"        # with the usual co-author trailer
git pull --rebase && git push
git tag v0.0.30 && git push origin v0.0.30
```

## 5. Watch it publish

```bash
gh run list --workflow Release --limit 1
gh run watch <id> --interval 30
```

- A flaky test job: `gh run rerun <id> --failed` on the same run. Do not tag
  again.
- A publishing job that fails (AMO refusing the notes, a registry): fix it on
  main and ask the maintainer whether to release the fix as the next version.
- When it is done: the GitHub release has the changelog's notes and the
  extension zips; the jobs say whether PyPI, npm, the images and the Firefox
  add-on were published (the extension is uploaded only when it changed). Tell
  the maintainer what was published and what was not.
