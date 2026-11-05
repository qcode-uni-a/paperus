# To do

Smaller tasks noted along the way; larger plans live in the other documents.

## Search

- **Embedding speed.** Measured 2026-11-05 on 24 cores with the library's
  own passages: bge-m3 2.8 passages/s, arctic-embed-m-v2 8.3,
  multilingual-e5-small 23.5 (more in the ML service's model list). The
  default is now arctic-embed-m-v2. Still to try: a reranker on the top
  hits, GPU support, and an evaluation with real questions (search.md).

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

## Browser extension

Noted 2026-11-05: as simple as possible.

- A default owner (oneself or a group) chosen once in the extension's
  settings; then **one click** saves the page's paper with its PDF, with no
  popup of choices. The PDF is downloaded in the browser (proxy, campus
  licences) and uploaded; the SHA-256 is sent first.
- Manifest V3 for Chrome and Firefox, connected with a personal access
  token that may only add papers.
- On arXiv (listings, search results, abstract pages) a small paperus icon
  next to each paper: one click saves it, a filled icon marks papers one
  already has (one lookup per page). Other sites (Google Scholar, PubMed)
  one at a time later.

## Formulas (needs discussion)

Noted 2026-11-05. Text read from PDFs garbles formulas: a PDF only stores
where each glyph sits, so fractions, sub- and superscripts and roots lose
their structure (`1 X+ϵ` for 1/(X+ϵ)). Search still works on the words
around them, and the PDF viewer shows them right; but passages for AI
assistants (MCP) and quotes cannot be trusted where formulas are.

Options, to discuss before building anything:

- **arXiv's LaTeX source** for arXiv papers: exact formulas, open access.
  Open: keep it as another file of the same version (a new file role
  "source", next to the PDF), or only use it once to replace the PDF's
  garbled passages and not keep it?
- **A formula-recognition model** in the ML service for other PDFs, as an
  optional, slow step per paper (e.g. Docling's formula step, MIT; check
  licences and speed first; Nougat's weights are non-commercial, Marker
  GPL, MinerU AGPL).
- Or leave it as it is.

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
- **Notifications**: a newer version of a paper was found,
  someone uploaded to a group, a workflow imported papers.
- **Workflows.** Scheduled jobs with rules, e.g. every night query arXiv for
  new papers matching rules and import them (into an inbox).
- **OCR** for scanned PDFs and handwritten notes.
- **Database maintenance.** Check whether Postgres needs scheduled work
  beyond autovacuum (e.g. reindexing vector indexes) and run it nightly.
- **Storage on slow disks or network shares** with a fast local cache, as
  other self-hosted libraries do. Less pressing without preview images; revisit with them.
- **Preview images** (first page thumbnails): only if a design needs them,
  e.g. a grid view or richer collection stacks.
- **Mobile app** and **desktop app with a local cache** (offline reading).
- **Very late (v2 or v3): an Overleaf replacement.** Start with git
  integration and LaTeX built on the server; needs many design decisions.
