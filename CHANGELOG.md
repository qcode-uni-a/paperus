# Changelog

## Unreleased

- **Import a library** (Add → Import a library): from Zotero, JabRef,
  Mendeley, EndNote and others, as BibTeX, RIS or CSL-JSON, alone or
  zipped with the PDFs. Papers already here are recognized and not added
  twice (importing again is safe); JabRef groups become collections,
  keywords tags, notes notes, and citation keys stay. Runs in the
  background with progress and a report of missing files. For very large
  libraries: `paperus import <zip|folder> --user <name>` on the server.
- **Notes**: your own writing about papers, in Markdown with formulas
  (rendered like Markdown files). A note can be about several papers (at a
  page) or none, sits in collections next to papers, and belongs to you or
  a group like everything else. Written on its own page with autosave;
  someone else's newer save is never overwritten silently; earlier
  versions can be brought back. Notes are searched with the papers (by
  words and by meaning), shown on each paper they are about, and can be
  downloaded as Markdown. AI assistants read them and, with the new right
  "Write and change notes", write them.
- **Citation export**: BibTeX and CSL-JSON for a paper (⋯ → Copy or
  Download BibTeX), a collection (⋯ → Export, with or without the
  collections inside) or everything, also for AI assistants
  (`export_citations`). BibTeX as Zotero writes it (keys like
  `gan_prizes_2026`, same field order and title protection), arXiv papers
  with `eprint` as arXiv does; citation keys from Better BibTeX are kept.

## 0.0.4 (2026-11-05)

AI assistants: paperus speaks MCP, with access tokens.

- **AI assistants (MCP)**: paperus speaks MCP at `/mcp`, so Claude, Cursor
  and others can search the library, read passages and papers, list
  collections and tags, download the files (PDFs), see what their token
  allows, and (if allowed) tag papers and add them by DOI, always citing
  links into paperus. Search results are grouped by paper, with abstracts
  on request, and kept compact to save the assistant's tokens. See
  [docs/ai.md](docs/ai.md).
- **Access tokens** (Settings): for AI assistants and scripts, with rights
  from presets or one by one, optionally only some owners, an expiry; shows
  the setup for Claude Code, Claude Desktop and Cursor.

## 0.0.3 (2026-11-05)

Backups, a first start in the browser, and merging duplicates.

- **Backups** (Administration → Backups): now or daily/weekly at a chosen
  hour, keeping the newest N; the database and optionally the files (each
  backup copies only new files). Restore with `paperus backup restore`;
  older backups are brought up to date while restoring. See
  [operations](docs/operations.md#backups).
- **First start in the browser**: create the administrator, or restore a
  backup found in the backup folder. Before restoring, a check shows where
  each file comes from (storage, backup) and warns about missing ones.
- **Merge duplicates**: "Merge into…" in a paper's ⋯ menu suggests papers
  with the same identifier or file and moves versions, files, tags and
  collections over (as far as one's rights allow); the merged paper goes to
  the trash.

### Upgrading from 0.0.2

Add a backup folder to `.env` (`BACKUP_LOCATION`, best on another disk) and
the matching line to `compose.yaml` (see `deploy/`), then turn on a schedule
under Administration → Backups. The database migrates on start (nothing to
do).

## 0.0.2 (2026-11-05)

Groups: private papers, shared ones, and who may do what.

- **Groups and owners**: every paper, tag and collection belongs to a person
  or a group. Groups nest (faculty, chair, project); members of a group are
  members of the groups inside it. Roles: reader, member, admin. Site
  administrators create top-level groups; group admins manage people and
  subgroups (Manage → Groups), with a reminder that licences must allow
  sharing. Lists, search and downloads show only what a person may see,
  mixed in one list; a small shared icon (click: which group) marks group
  papers, tags and collections. Papers, tags and collections can be given
  to a group or taken back (Edit). Private tags and collections on group
  papers stay private; a group's tags can also go on one's own papers.
  Everything from before belongs to a first group, "Shared library". Who
  may do what: [docs/permissions.md](docs/permissions.md).
- **Settings**: owner of new papers, tags and collections, theme, password.
- **Recent**: papers by latest activity (opened by me, or added or changed).
- **Users** in the browser (Administration → Users): create, new password,
  administrator rights, deactivate. People can leave groups; groups can
  move inside other groups.
- A one-time hint after the first added paper explains owners.
- Tag colours (18), descriptions and usage; Manage pages for collections
  (a tree with drag and drop) and tags.

### Upgrading from 0.0.1

The database migrates on start (migrations 0006–0011, nothing is lost):
everything added so far belongs to a new group, "Shared library", with
every existing user as a member (administrators as its admins). Give
papers to other groups or back to their people from there.

### Known limitations

- Two people adding the same paper independently get two items; merging
  duplicates comes later.
- A group's collection cannot yet appear inside a private collection.
- No MCP server for AI assistants, no BibTeX export, no backups command yet.
- The Python packages and the TypeScript client are not published yet.

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
