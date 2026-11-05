# Changelog

## 0.0.1 (2026-11-05)

First version, for trying paperus in a small group. Expect breaking changes.

### What works

- **Library**: add papers by DOI, by hand (notes, meeting notes, lecture
  notes), or by dropping files anywhere in the window. Uploaded PDFs get their
  title, authors and identifiers from a DOI or arXiv ID found in them.
- **Versions**: preprints, published versions, editions, each with their own
  identifiers and files; the published version is cited by default.
- **Search** over the full text by words and by meaning (embeddings from the
  paperus-ml service), combined, with search options and type filters.
- **Reading**: PDFs open in the browser (PDF.js), search results jump to the
  page.
- **Notes**: text and Markdown files are shown as pages, Markdown with
  tables, checklists and formulas (KaTeX).
- **Tags and collections**: tag items, file them into collections that can
  hold other collections; each collection shows its latest papers as a
  stack. Add to a collection from its page: from the library, by uploading
  or by DOI, or by dropping files on it.
- **Duplicates**: uploading a file that is already in the library makes no
  new item (the browser skips the upload where it can), and another file of
  a paper already in the library (same DOI) joins that item.
- **Trash**, change numbers for syncing, edits that never overwrite someone
  else's.
- **Administration**: users (as a placeholder), jobs, machine learning
  settings including the embedding model, server stats.
- **Website** with light and dark themes, usable on phones.
- **Installation** with Docker Compose (server, worker, ML service, Postgres)
  behind a single port, also behind a reverse proxy. The Python packages
  (`paperus`, `paperus-ml`) and the TypeScript client follow in a later
  release.

### Known limitations

- No groups or permissions yet: every user sees every item.
- Only username and password login; no university login (OIDC/SAML).
- Search by meaning is slow to set up on CPU (about 1.5 passages per second
  with BGE-M3).
- Tags and collections are shared by everyone; owners (a person or a group)
  come with groups.
- Duplicates that were already in the library are not merged yet.
- No MCP server for AI assistants, no BibTeX export, no backups command yet.
