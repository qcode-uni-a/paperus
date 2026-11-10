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
  has been applied; the dev database holds test data, so never reset it
  without asking.
- Frontend and browser extension in TypeScript.
- The app (`app/`): Tauri 2, Rust; `cargo fmt`, `cargo clippy -- -D warnings`.
- Tests: server and ML service keep line coverage above 95% (CI checks with
  `pytest --cov`); browser journeys in `e2e/` (Playwright, `npm test` there);
  fluent mode's page layouts on layout twins (`server/tests/twins/`, in
  pytest): never check in a paper's PDF, only its measured layout. Raise
  `page_layout.VERSION` when a change alters layouts (stored ones are then
  made again).

## Guidelines

- Licence: Apache-2.0 (`LICENSE`). Don't copy code from AGPL projects
  (Immich, Zotero); ideas are fine. Note other borrowed code and its licence
  in `THIRD_PARTY.md`.
- When creating commits, include a co-authorship trailer for the tool.
- Don't register domains or package names without being asked.
