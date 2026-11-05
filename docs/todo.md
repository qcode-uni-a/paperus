# To do

Smaller tasks noted along the way; larger plans live in the other documents.

## Search

- **Embedding speed.** bge-m3 in fp32 embeds about 1.5 chunks/s on a
  24-core CPU (measured 2026-11-05), so a 10,000-paper library would take
  days, not hours as estimated in [search.md](search.md). Compare int8
  exports, batch sizes and thread settings, and a smaller model.

## Ideas to decide later

Collected 2026-11-05, roughly in priority order; each needs a design first.

- **Backups (high priority).** From the admin page and on a schedule: the
  database alone or database plus files, with the paperus version and
  migration stored alongside, so a backup can be restored into the same or
  a newer version.
- **Personal access tokens.** For scripts, the MCP server (an AI assistant
  acting for its user) and the browser extension, instead of the login
  session. In Settings: create a named token, shown once, with scoped
  rights like Immich's API keys: pick permissions per kind and action
  (e.g. `papers.read`, `papers.write`, `files.download`, `search`,
  `tags.write`, `collections.write`, `groups.read`), with presets ("read
  only", "AI assistant: search and read", "everything"), optionally only
  for some owners (just me, or one group), and an expiry; see when each
  was last used; revoke. Stored only as a hash like login sessions; a token acts
  with its owner's permissions narrowed by its scopes (never more);
  deactivating a user stops their tokens. Administrators see that tokens
  exist, not their values.
- **Onboarding.** Create the first administrator in the browser on first
  start, like Immich, instead of the command line.
- **Feature parity with Zotero** as the general goal: citation styles and
  export, browser connector, notes and annotations, Word/LibreOffice
  plugins, Zotero import, related items, duplicates merging.
- **Start page.** A good default (e.g. recently added, recently opened,
  most used) with simple sorting and filtering; paperless-ngx's custom
  dashboards feel like overkill.
- **Archive.** Like the trash, but kept for good: archived items are left
  out of search and lists unless asked for.
- **Smart collections.** Rule-based first (tags, type, year, library), later
  by meaning (papers similar to a query or a set of papers).
- **Notifications**, like Immich: a newer version of a paper was found,
  someone uploaded to a group, a workflow imported papers.
- **Workflows.** Scheduled jobs with rules, e.g. every night query arXiv for
  new papers matching rules and import them (into an inbox).
- **OCR** for scanned PDFs and handwritten notes.
- **Database maintenance.** Check whether Postgres needs scheduled work
  beyond autovacuum (e.g. reindexing vector indexes) and run it nightly.
- **Storage on slow disks or network shares** with a fast local cache, as
  Immich does. Less pressing without preview images; revisit with them.
- **Preview images** (first page thumbnails): only if a design needs them,
  e.g. a grid view or richer collection stacks.
- **Mobile app** and **desktop app with a local cache** (offline reading).
- **Very late (v2 or v3): an Overleaf replacement.** Start with git
  integration and LaTeX built on the server; needs many design decisions.
