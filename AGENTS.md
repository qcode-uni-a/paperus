# paperus: notes for coding agents

Design phase: start with `README.md` and `docs/`. `docs/decisions.md` lists
what is decided and what is still open; don't re-open decided points without
a reason.

## Conventions (planned)

- Python server: uv, ruff, ty, pytest. Fully annotate functions (ruff `ANN`).
- Pre-commit hooks (`.pre-commit-config.yaml`): `uvx pre-commit install` once
  per clone; `uvx pre-commit run --all-files` to check everything.
- Imports at the top of the file, except optional dependencies.
- Database migrations: until the first deployment with data to keep, change
  the single initial migration instead of adding new ones. After that, add a
  migration per change and never edit one that has been applied.
- Frontend and browser extension in TypeScript.

## Guidelines

- Licence: Apache-2.0 (`LICENSE`). Don't copy code from AGPL projects
  (Immich, Zotero); ideas are fine. Note other borrowed code and its licence
  in `THIRD_PARTY.md`.
- When creating commits, include a co-authorship trailer for the tool.
- Don't register domains or package names without being asked.
