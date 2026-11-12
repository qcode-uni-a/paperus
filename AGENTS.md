# paperus: notes for coding agents

Design phase: start with `README.md` and `docs/`. `docs/decisions.md` lists
what is decided and what is still open; don't re-open decided points without
a reason.
Planned work and ideas are GitHub issues (`gh issue list`), not a file;
close them from commits with "Fixes #n".

## Conventions (planned)

- Python server: uv, ruff, ty, pytest. Fully annotate functions (ruff `ANN`).
- Pre-commit hooks (`.pre-commit-config.yaml`): `uvx pre-commit install` once
  per clone; `uvx pre-commit run --all-files` to check everything.
- Imports at the top of the file, except optional dependencies.
- Database migrations: add a migration per change and never edit one that
  has been applied; the dev database holds test data, so never reset or
  downgrade it without asking. Fill in existing rows in the migration itself
  with SQL, not with the app's code (which changes after it), and test that
  in `server/tests/test_migrations.py` (downgrade, add data, upgrade,
  check). Then `paperus migrate` the dev database at once (the dev API
  reloads the new models and fails on missing columns) and restart the dev
  worker.
- Frontend and browser extension in TypeScript.
- The app (`app/`): Tauri 2, Rust; `cargo fmt`, `cargo clippy -- -D warnings`.
- Tests: server and ML service keep line coverage above 95% (CI checks with
  `pytest --cov`; the server's in parallel, `pytest -n 8 --cov`, a test
  database per worker); browser journeys in `e2e/` (Playwright, `npm test`
  there); fluent mode's page layouts on layout twins (`server/tests/twins/`, in
  pytest): never check in a paper's PDF, only its measured layout. Raise
  `page_layout.VERSION` when a change alters layouts (stored ones are then
  made again). The extension reads publishers' pages on page twins
  (`extension/twins/`, `npm test` there): never check in a saved page, only
  its twin, with parody names (`extension/twins/README.md`).

## Checking a change

- Others (people and agents) push to main too: `git pull --rebase` before
  pushing, and after pulling check that a new migration's number is free.
- Web changes: look at them before committing, in light and dark and at
  phone width (360 px), e.g. screenshots from a throwaway Playwright spec in
  `e2e/tests/` that is not committed (dismiss "Getting started" on the fresh
  test server; let transitions end before a screenshot).
- The browser extension: in `extension/`, `npm run check`, `npm test`, `npm
  run build` and `npx web-ext lint -s dist/firefox`. A change in what it
  does or may do (permissions, what it sends and when) goes into its
  `PRIVACY.md`, `README.md` and the notes for Mozilla's reviewers
  (`amo-metadata.json`, `approval_notes`, at most 2,900 characters). Say
  what was not tried in a real browser, Firefox especially.
- CI stays green. A test that fails now and then is a bug in the test or the
  app: find since when (`gh run list`, `gh run view <id> --log-failed`),
  repeat it (`npx playwright test <file> --repeat-each 5`; WebKit with `npm
  run test:webkit` in `e2e/`, in Docker), and fix it; re-run a job
  (`gh run rerun <id> --failed`) only for a failure understood to be
  outside paperus.

## Guidelines

- Licence: Apache-2.0 (`LICENSE`). Don't copy code from AGPL projects
  (Immich, Zotero); ideas are fine. Note other borrowed code and its licence
  in `THIRD_PARTY.md`.
- When creating commits, include a co-authorship trailer for the tool.
- Releases: only on the maintainer's go; `scripts/release.sh` and the steps
  in `.claude/skills/release/SKILL.md`.
- Don't register domains or package names without being asked.
