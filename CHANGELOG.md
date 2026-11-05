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
- **Trash**, change numbers for syncing, edits that never overwrite someone
  else's.
- **Administration**: users (as a placeholder), jobs, machine learning
  settings including the embedding model, server stats.
- **Website** with light and dark themes, usable on phones.
- **Installation** with Docker Compose (server, worker, ML service, Postgres);
  Python packages `paperus` and `paperus-ml`; TypeScript client `paperus`.

### Known limitations

- No groups or permissions yet: every user sees every item.
- Only username and password login; no university login (OIDC/SAML).
- References in papers also match searches by meaning.
- Search by meaning is slow to set up on CPU (about 1.5 passages per second
  with BGE-M3).
- No MCP server for AI assistants, no BibTeX export, no collections, no
  backups command yet.
