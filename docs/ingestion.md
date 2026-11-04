# Ingestion

## Adding items

- Paste a DOI, arXiv ID, PubMed ID or URL; drop in PDFs or other files; click
  the browser extension; import from Zotero, Mendeley or BibTeX.
- First screen for new users: "Drop PDFs here" or "Import from Zotero".
  Nothing to configure.

## Metadata

- Easy case (most recent papers): DOI → Crossref/OpenAlex. arXiv and PubMed IDs
  the same way.
- Hard cases:
  - no DOI in the file: extract the title with GROBID, search Crossref/OpenAlex
    by title (wrong matches happen, so show confidence and ask);
  - preprint and published version of the same work: link them (see versions);
  - books and non-STEM: ISBN via Open Library or national library catalogues;
  - duplicates and manual corrections: keep field-level provenance so a later
    lookup never overwrites a manual edit.
- Never let AI change bibliographic metadata without the user seeing it.

## PDFs

Order when an item has no PDF yet:

1. **Server, open access only**: Unpaywall, arXiv, PubMed Central, bioRxiv,
   publisher OA links. Re-check periodically (e.g. weekly), since open
   versions often appear later.
2. **Browser**: the extension downloads the PDF in the user's own session
   (including the university proxy or Shibboleth) and uploads it.
3. **Manual**: the item stays metadata-only with status "no PDF"; a
   "Get PDF" button opens the publisher page through the university's proxy
   prefix (e.g. EZproxy, configurable) and the extension catches the download.

The server never downloads from publishers itself: licences, the risk of the
publisher blocking the whole campus IP range, and cookie-bound links.

Details:

- Check for `%PDF` magic bytes; a 200 response is often a login page.
- The extension sends the SHA-256 first and skips the upload if the user can
  already see a file with that content. Never answer for files the user
  cannot see (that would reveal private drafts or licensed PDFs of other
  groups); upload anyway and deduplicate the blob on the server.
- Resumable uploads (e.g. tus) for large scans.
- Record where each PDF came from (open access, user upload, manual), which
  matters for sharing rules.
- Items are deduplicated by DOI, so a PDF one member adds is available to the
  group, subject to the group's sharing settings.

## Browser extension

- Read `citation_*` meta tags (`citation_title`, `citation_doi`,
  `citation_pdf_url`, …), DOI patterns, JSON-LD and COinS.
- Fallback: Zotero's translation-server (AGPL, run unmodified as a separate
  service) for site-specific translators.

## Versions of a document

- One item, several versions, each with its own identifiers, metadata and
  files (see architecture). Works the same for papers (preprint,
  published), lecture notes (editions per semester), books (editions) and
  single-version sources (meeting notes).
- Citations use the preferred version: published by default, the preprint
  otherwise, or the one the user pinned.
- Adding an identifier that belongs to a version of an existing item finds
  that item; adding a known preprint's published DOI adds a version.

### Finding published versions of preprints

A background job checks items whose preferred version is a preprint, on
ingest and then periodically (e.g. weekly, like the open-access check).
Sources, all free, checked 2026-11-04 with arXiv 2006.10256 (NumPy paper):

| Source | What it gives | Result for the example |
| --- | --- | --- |
| arXiv API (`export.arxiv.org/api/query`) | `doi` and `journal_ref`, entered by authors | Nature DOI, "Nature 585, 357 (2020)" |
| DataCite (`api.datacite.org/dois/…`), for arXiv DOIs | `relatedIdentifiers`, `IsVersionOf` | Nature DOI |
| OpenAlex (`api.openalex.org/works/doi:…`) | One work with all locations, each with `version` (submitted, accepted, published) | Nature, PubMed Central as published; arXiv as submitted |
| Crossref (`api.crossref.org/works/…`) | `relation`: `is-preprint-of` / `has-preprint`, deposited by bioRxiv, SSRN, publishers | Depends on deposits; empty for the bioRxiv example checked |

When a published DOI is found: look up its metadata and add it as a new
version labelled with where it came from, or, if the published DOI already
belongs to another item, suggest merging the two. Shown as "Published version
available" on the item (and in the AI inbox when an AI client is connected).
Fallback without links: Crossref search by title and first author, only as a
suggestion with a confidence score, never added automatically.
- Link preprint ↔ published automatically via arXiv `journal-ref` and
  Crossref/OpenAlex relations; offer to merge when both are added.
- Annotations stay on their version, anchored by text quote, so they can be
  carried over to a newer version on request.
- Internal drafts: private to authors or the group by default.

## Other kinds of sources

Everything is an item with a type and a source; same pipeline, no separate
editors.

| Source | How | When |
| --- | --- | --- |
| Uploads: PDF, DOCX, PPTX, Markdown, images | Same pipeline; Docling for Office files and slides | First version |
| Notes written in the app | Markdown | First version |
| GitLab/GitHub repos (LaTeX/Markdown lecture notes) | Link repo + path; pull on webhook or nightly; index the source text; optionally keep the CI-built PDF | Second step |
| Overleaf | Via Overleaf's git integration (paid plans, Server Pro), then like a git repo | Second step |
| Handwritten notes, whiteboard photos | Image + transcription; printed text via server OCR; handwriting via the user's own AI over MCP (no GPU needed); optional server vision model later | Second step |
| Meeting notes, transcripts | Upload or create via MCP, labelled AI-written if so; Teams/Zoom transcript import | Later |

Meeting notes contain personal data: default visibility to participants, offer
a retention setting.

## Frequent updates without clutter

- Chunks stored by content hash; a version is a manifest of chunk hashes.
  A typo fix in 100 pages = 1 new chunk + 1 embedding (~4 KB).
- Structure-aware chunking keeps boundaries stable; fixed-size sliding windows
  would shift every chunk after an insertion. Content-defined chunking for
  unstructured files.
- For git sources store the commit ID and manifest, not file copies. Keep the
  built PDF only for the latest and tagged versions.
- Coalesce frequent syncs (e.g. one visible version per day, or on tags, or
  when more than a few percent changed).
- Search covers the latest version by default; unreferenced old chunks are
  garbage-collected.

## Migration from Zotero

Import via the Zotero Web API or the local `zotero.sqlite` + storage folder.
Keep items, collections, tags, notes, PDF annotations and Better BibTeX
citation keys (existing LaTeX documents depend on them). Option: index an
existing PDF or Zotero storage folder read-only, like Immich's external
libraries.
