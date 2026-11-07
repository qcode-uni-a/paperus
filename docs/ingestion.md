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

## Identifying uploaded files

A dropped file becomes an item titled after the file, marked as a
placeholder. After text extraction, in the same transaction:

1. DOIs and arXiv IDs on the first two pages are looked up; the first whose
   registry title also appears on those pages wins (papers cite other DOIs).
2. Otherwise a plausible title embedded in the PDF replaces the file name.
3. A DOI that is already in the library is left alone for now; merging
   duplicates comes later. Later: title search (Crossref) as a suggestion,
   GROBID for files without identifiers.

Manual metadata is never replaced; only placeholders are.

## PDFs

Order when an item has no PDF yet (Manage → Missing; by itself in the
background with Administration → Server → Open-access copies):

1. **Server, open access only** (done): the journal's own open copy where
   OpenAlex lists one (published or accepted version), else the paper's
   arXiv version (found via OpenAlex by its DOI; added as the paper's
   preprint version, with its details from arXiv's DOI), else what
   Unpaywall knows (with the contact email). Publishers often refuse
   downloads by servers even of open papers (ACS answered 403 in a test);
   then the browser gets them. Manage → Missing also lists published
   papers with only their preprint's PDF ("Only the preprint"); open
   access there means the journal's copy only. Later: re-check
   periodically, since open versions often appear later.
2. **Browser**: the extension downloads the PDF in the user's own session
   (including the university proxy or Shibboleth) and uploads it; on the
   publisher's page of a paper paperus has, by its DOI, into that paper
   (its shown version, i.e. the published one). Later: the Missing page
   asking the extension to fetch many at once (background tabs; one
   permission prompt for publisher sites). The website itself cannot: the
   browser does not let a page read other sites' files.
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

**Built** (`server/src/paperus/published.py`, Administration → Server →
Published versions, on by default): every hour up to 40 preprints (with an
arXiv ID, without a journal version), each at most once a month, are looked
up: arXiv's API first (the DOI the authors entered, 50 papers per request,
3 s apart), else OpenAlex (the DOI of the work it links the preprint to).
The version is added only if its title matches (nearly the same text, or
at least half of the longer words: papers are often renamed on
publication). On one physicist's library (130 preprints, checked
2026-11-07): 55 found and taken, 5 turned away (a wrong DOI on arXiv,
OpenAlex links to other papers of the same group, strong renames). Not
built: DataCite (its links for arXiv papers come from the same author
entries), Crossref relations, the title search fallback. The journal PDF
then comes with the open-access copies (if on) or Manage → Missing.

The original plan: a nightly background job checks items whose preferred
version is a preprint (also once on ingest). When it finds a newer version, it adds it and tries
to obtain its PDF the usual way (open access on the server, otherwise
"Get PDF" for the user's browser).
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

### Reference lists of papers

**Built** (`server/src/paperus/item_references.py`, Administration →
Server → Reference lists, on by default): every hour up to 40 papers
(never looked at first), and each paper right after its file is read, get
their reference list, from the best source there is:

1. a paper with an arXiv ID: arXiv's LaTeX source (one request to
   `arxiv.org/e-print/`, at least 3 s apart), read as the import of LaTeX
   sources reads it: the `.bbl`, else `thebibliography`, else the `.bib`
   entries the `.tex` cites;
2. a paper with a DOI: Crossref's record (`api.crossref.org/works/{doi}`),
   with the references its publisher deposited (some deposit DOIs only);
3. else the PDF's own list, from its stored text: split where references
   are numbered (`[12]`, `12.`, AIP's `12A. Name`, counted up from 1),
   else, best effort, where an author-year entry starts (`Smith, J.` after
   the end of the one before). Not split: other layouts (initials first
   without numbers, `1)`); a page's running head or footer may stay in a
   reference.

Only identifiers are taken in the background: DOIs, arXiv IDs and links
in the references (no searching). A reference matches a paper the person
can see by its DOI or arXiv ID (not in the trash; archived papers too,
since adding them would find them). The paper's page lists the references:
papers in the library as links, the others with their DOI or arXiv link
and **Import** (adds it as Add → DOI does), text-only ones with **Find**
(Crossref's search, taken only if certain, as in the LaTeX import);
**Import all** adds every reference with an identifier into a collection
"References of …", as an import. "Cited by" lists the papers whose
references have the paper's DOI or arXiv ID. A paper without list is
looked at again when it gets a version or file, or when someone asks
("Look again"); a list found stays until one is found again.

Checked on three papers of a physicist's library (2026-11-07): an arXiv
paper with a `.bib` (376 references, 315 with a DOI or arXiv ID; the
source's Emacs-style `@Comment` line first broke the BibTeX reader, now
fixed), an APS paper via Crossref (50 references, 48 with DOIs, deposited
without text), and an IOP paper's PDF (69 references, numbered, split
right; IOP prints no DOIs, so 1 identifier: Find helps there).

## Other kinds of sources

Everything is an item with a type and a source; same pipeline, no separate
editors.

| Source | How | When |
| --- | --- | --- |
| Uploads: PDF, DOCX, PPTX, Markdown, images | Same pipeline; Docling for Office files and slides | First version |
| Notes written in the app | Markdown | First version |
| GitLab/GitHub repos (LaTeX/Markdown lecture notes) | Link repo + path; pull on webhook or nightly; index the source text; optionally keep the CI-built PDF | Second step |
| Overleaf | Via Overleaf's git integration (paid plans, Server Pro), then like a git repo | Second step |
| Handwritten notes, whiteboard photos | Image + transcription; printed text via server OCR (done: scanned PDFs and images, see search.md); handwriting via the user's own AI over MCP (no GPU needed); optional server vision model later | Second step |
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

## Import from other reference managers

Decided 2026-11-05; built in steps (see the changelog).

| Format | Exported by | Brings along |
| --- | --- | --- |
| Zotero RDF (zip with "Export Files" and "Export Notes") | Zotero | Papers, files, collections, tags, child and standalone notes, related papers |
| BibTeX / BibLaTeX (`.bib`, or a zip with the files) | JabRef, Zotero, Mendeley, most others | Papers, citation keys, `file` links, keywords as tags, JabRef groups as collections, `annote`/`comment` as notes |
| RIS (`.ris`) | Mendeley, EndNote, Citavi, publishers | Papers, keywords as tags, notes, file links |
| CSL-JSON | Zotero, Pandoc | Papers (metadata only) |
| LaTeX reference list: arXiv source (`.tar.gz`, or by arXiv ID), `.bbl`, zip of a LaTeX project | arXiv, BibTeX/biber, Overleaf | The paper's references, looked up by DOI/arXiv ID (else found on Crossref), in a collection named after the paper |

Mendeley's exports do not include its collections.

What came with a paper's details rather than from a person (Zotero's
"automatic tags": arXiv categories, a publisher's subjects; Mendeley's
author keywords, i.e. its `keywords` beyond `mendeley-tags`) is imported
as the paper's *keywords*, kept apart from tags: shown on a line of their
own on its page, left out of the tag list and the library's rows unless
asked for; + makes one a tag, and Manage → Tags → Remove all keywords
takes them all off. Importing an export again sorts the keywords an
earlier import took as tags. (Stored as tags with the source
"automatic".)

- **How**: upload the file (or a zip with it and the files) in the browser
  and choose the owner (oneself or a group); the import runs as a job with
  a progress page. For very large libraries an administrator can run
  `paperus import <file> --user <name>` on the server.
- **Each format is read into one common form** (CSL-JSON metadata,
  identifiers, tags, collection paths, notes as Markdown, files), so the
  rest of the import is the same for every format.
- **Duplicates**: a paper the person can already see (same DOI, arXiv ID
  or file) is not added again; its new tags, collections, notes and files
  are added to the existing one. Within one import, the same paper twice
  becomes one paper.
- **Kept as they were**: collection structure, tags (Zotero's automatic
  tags too), citation keys (Better BibTeX, JabRef), notes (HTML converted to
  Markdown), the metadata as exported (no lookups that could overwrite it;
  missing identifiers can be looked up later as for uploads).
- **Files** are stored like uploads (deduplicated by content) and read for
  search; a missing file is listed in the report, not an error.
- **Report** at the end: how many papers were added, found already, and
  which files or entries could not be read.
- **References of a LaTeX paper** (`paperus.importing.bbl`, `references`):
  from an arXiv source (uploaded, or fetched by arXiv ID or link with one
  request to `arxiv.org/e-print/`), a zip of a LaTeX project, or a `.bbl`
  alone. The `.bbl` is preferred: it is exactly the list the paper prints,
  while a `.bib` beside it often holds many more entries; without one, a
  `thebibliography` in the `.tex`, else the `.bib` limited to the keys the
  `.tex` cites. Read are BibLaTeX's `.bbl` (fields), REVTeX/natbib styles
  (`\bibinfo` fields) and plain styles (free text: DOIs, arXiv IDs, links).
  A reference with a DOI or arXiv ID gets its details from the registry as
  a paper added by DOI does; one without is searched on Crossref
  (`query.bibliographic`) and taken only if Crossref's score is at least 60
  (right matches scored 85-109, wrong ones 20-32 on real references), its
  first author is in the reference, and its title (or, in styles without
  titles, year, volume and first page) too. References with fields and a
  title are kept as they are when not found; free text without identifier
  is not added but listed in the report ("Not recognised: …"). Archives are
  read in memory, never unpacked to disk, with limits on members and size.
- **Zotero RDF** is read as an RDF graph (rdflib), so the XML layout does
  not matter; checked against a hand-made sample in Zotero's layout, still
  to be checked against a real export.
- **Not now**: Zotero PDF annotations (not in Zotero's exports; later via
  the Zotero Web API or the local database), sync instead of a one-off
  import, reading `zotero.sqlite` directly.
