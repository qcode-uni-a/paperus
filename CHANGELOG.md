# Changelog

## Unreleased

- **Profile picture editor**: move and zoom the picture in a circle, with
  previews at the sizes others see. Only the 256-pixel result leaves the
  browser; the server refuses pictures larger than 512 pixels on a side.
- The menu's Manage part sits at the bottom of the window; Administration
  is only in the profile menu, whose entries now have icons.

## 0.0.8 (2026-11-05)

The first release with packages besides the container images.

- **PyPI**: `paperus` (the server, worker and command line; the website
  comes with the container image) and `paperus-ml` (the ML service). The
  container images remain the way to install paperus.
- **npm**: `paperus`, the TypeScript client for the API.

## 0.0.7 (2026-11-05)

All settings in one place: background jobs, OIDC login, users leaving, a
readable copy of the library on disk; profile pictures, storage use and
Prometheus metrics.

- **More settings** (Administration → Settings):
  - Server: the public address (for links the server makes, e.g. for AI
    assistants), the contact email sent to metadata services, and the
    largest upload.
  - Trash: empty it automatically after some days (every night; off by
    default). Emptying also removes stored files nothing uses any more.
  - Logging: the log level of server and worker, without a restart.
  - Integrity checks: whether every file's stored contents are there
    (every Sunday night, or now), deeply also whether they are unchanged,
    and removing stored contents nothing uses any more.
- **OIDC login** (OpenID Connect: Keycloak, Authentik, Microsoft Entra,
  Google, Shibboleth's OIDC provider, …), set up in Administration →
  Settings → Authentication or right after creating the first
  administrator. Accounts are created on first login (or only for people
  added beforehand), linked by username, or linked by hand with "Link my
  account" (also in one's own settings); the identity provider's picture
  becomes the profile picture if there is none. Password login can be
  limited to administrators.
- **Profile pictures**: chosen in one's own settings (cut to a square and
  scaled down in the browser), shown in the menu, with group members and
  in Administration → Users.
- **Storage template**: a readable copy of the library on disk, each
  paper's files in folders and under names from a template (e.g.
  `{owner}/{first_author}_{journal}_{year}` gives
  `Chair/Lovelace_NatPhys_1843.pdf`), with a live preview; updated
  every night, as copies or hard links. paperus keeps storing files by
  content; only files it wrote are ever changed or removed. Docker:
  `COPY_LOCATION` in `.env`.
- **Users settings**: groups (with a role) that new accounts join, and
  handing a departed person's papers, notes, collections and tags to a
  group or another person (tags merge by name).
- **Authentication settings**: how long one stays logged in, the shortest
  password, and logging everyone out.
- **Job settings**: how many files are read, sent to the ML service and
  imported at the same time (applied by the worker within half a minute,
  no restart), and the hour of the night jobs; an overview of what runs
  when. The integrity check runs every Sunday, every night or not at all.
- **Prometheus metrics** for monitoring, on a port of their own (off by
  default): requests, searches, calls to the ML service, and the library's
  figures (papers, files waiting to be read, storage, background jobs, the
  last backup); the ML service reports its requests, batch times and
  loaded models. See docs/operations.md.
- **Storage use**: how much space the library takes and how much is free,
  at the bottom of the menu and in Administration → Server stats (with the
  backups); also as Prometheus metrics.
- **Empty trash** on the trash page: deletes for good what one may change.
- The search bar is hidden in the administration; the settings sections
  start folded, each with an icon and how it is set at a glance.
- The backups page mentions restoring a backup on a new server from the
  welcome page, without commands.

## 0.0.6 (2026-11-05)

A new look, faster search by meaning with a choice of
models, tidying up the library (duplicates, unsorted papers, favourites),
and fixes from a code review, including security fixes for access tokens.

- **Messages when background work is done**: after uploading more than
  five papers, a note says they are being read, and a message follows when
  all are ready (with how many need their details by hand, linking to
  Unsorted). An import says when it is done, with its summary, also after
  leaving the import page. As long as paperus is open in the browser.
- **A new look**: the search moved into the top bar (on
  every page; "/" jumps to it), the menu got icons and a rounded highlight
  for the current page, buttons are rounded, and pages start right next to
  the menu. Administration → Settings is one page of sections that open
  and close (the open ones stay in the address); messages appear in the
  corner and close themselves.
- **Search shows more papers**: at most three passages per paper, with
  "More from this paper" for the rest, so one paper with many hits no
  longer fills the list (the API: `per_item`, and `item` to search within
  one paper; AI assistants get the same).
- **Favourites**: star papers (☆ next to the title, in lists and on the
  paper); "Favourites" in the sidebar lists them. Each person has their
  own stars, readers too.
- **Pinned collections**: a collection's ⋯ menu pins it to the sidebar,
  below Collections, for quick access.
- **Manage → Duplicates**: papers that look like the same paper twice
  (same DOI or arXiv ID, same file, or the same title), typical after
  importing from several programs, with a recommendation which to keep and
  why. Merging shows beforehand what moves and what stays; "Not the same
  paper" hides a pair for good.
- **Manage → Unsorted**: papers whose details could not be found (no DOI
  or arXiv ID in the file). Enter the DOI or arXiv ID to look them up.
- **More models for search by meaning** (Administration → Settings →
  Machine learning): Snowflake Arctic Embed M/L v2, GTE multilingual,
  multilingual-e5 base/large and bge-m3 in int8, next to bge-m3 and
  e5-small. Each shows its published retrieval scores (English, German,
  multilingual), size and licence, and "Measure speed" times it on your
  server, with how long the library would take. A clear warning before
  switching: the library gets new vectors (the old ones are kept).
- **New installations use arctic-embed-m-v2**: about three times faster
  than bge-m3 and at least as good in published retrieval scores.
  Installations already using bge-m3 keep it until an admin switches.
- **ML service settings in the administration**: the CPU cores it may use
  (a slider), and it keeps the model in use loaded. The server sends the
  settings to the ML service, also after either restarts. One batch at a
  time per model, so simultaneous requests no longer fight over the cores.

- **Fixes from a code review**:
  - Security: an access token limited to some owners could still read the
    person's private papers, notes and files by id; a site administrator's
    token saw every group. Personal settings (stars, pins) are closed to
    tokens, and a test pins the decision for every API route.
  - Import: a crafted Zotero file or zip can no longer stall or flood the
    worker; one bad entry no longer spoils the rest; nothing is imported
    twice; uploaded exports are deleted afterwards.
  - Notes: switching between notes, filing or linking them, or two saves at
    once can no longer lose or mix up text; leaving with unsaved text warns.
  - Merging papers keeps their notes and stars; a group with notes cannot
    be deleted by accident.
  - Search by meaning answers at once (by words) while a model is still
    downloading, instead of waiting.

## 0.0.5 (2026-11-05)

Notes, importing a library from Zotero, JabRef or Mendeley, and citation
export.

- **Import a library** (Add → Import a library): from Zotero, JabRef,
  Mendeley, EndNote and others, as Zotero RDF, BibTeX, RIS or CSL-JSON,
  alone or zipped with the PDFs. Papers already here are recognized and not
  added twice (importing again is safe); Zotero's collections, child and
  standalone notes come along, JabRef groups become collections,
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
