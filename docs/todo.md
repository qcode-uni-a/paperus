# To do

Smaller tasks noted along the way; larger plans live in the other documents.

## Search

- **Embedding speed.** bge-m3 in fp32 embeds about 1.5 chunks/s on a
  24-core CPU (measured 2026-11-05), so a 10,000-paper library would take
  days, not hours as estimated in [search.md](search.md). Compare int8
  exports, batch sizes and thread settings, and a smaller model.

## Sidebar and library

Noted 2026-11-05.

- **Favourites**: mark papers (and notes?) with a star; own sidebar entry.
- **Recently read**: own sidebar entry for what one opened. The Recent page
  already has "Opened by me"; perhaps split it into two entries.
- **Quick links**: pin collections to the sidebar.
- **Manage → Unsorted**: papers whose details could not be found
  automatically (no DOI or arXiv ID found, title only from the file), to
  fix by hand.
- **Manage → Duplicates**: likely duplicates across the library (same
  identifier or file, similar titles) with a recommendation, merged by hand
  with the existing merge preview.

## Groups and notes

Noted 2026-11-05.

- **Replies on notes**: a comment thread on a note, apart from its text,
  so a group can discuss without editing it; together with PDF
  annotations (highlights with comments), which work much the same.
- **"Share with group…"** as the wording for giving a paper to a group
  (the same handover, but it reads like sharing in Google Photos).
- **"Added by"** on group papers, so people see who brought a paper in.
- **Sharing with single people** via small ad-hoc groups ("Anna & Ben"),
  so the owner model stays as it is.

## Ideas to decide later

- **OAuth for MCP**, so claude.ai and ChatGPT can connect as custom
  connectors (they do not take a token header); later delegating to the
  university's login.

Collected 2026-11-05, roughly in priority order; each needs a design first.



- **Feature parity with Zotero** as the general goal: citation styles and
  export, browser connector, notes and annotations, Word/LibreOffice
  plugins, related items.
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
