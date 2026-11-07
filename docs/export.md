# Export

Decided 2026-11-07. Everything a person can see, to take home: one SQLite
database with paperus' own tables and a folder of the files, in zips; or,
for other programs, a Zotero RDF, BibTeX (JabRef) or RIS (Mendeley) file
beside the files (see [For other programs](#for-other-programs)).

## Exporting

- **Website**: Settings → Export. By default everything one sees, with
  the files, in paperus' own format. Choices: the format (paperus,
  Zotero, JabRef, Mendeley), whose (my own papers and each group's; at least one),
  what comes along (files, notes, tags and keywords, collections,
  reference lists, archived papers; all ticked at first), also the trash
  (off at first), and only one collection (also from a collection's menu:
  "Export with files and notes…"). The size is estimated before starting.
  The export is written in the background; a message says when it is
  ready, and the section lists one's exports with their zips to download
  for a day (24 hours), then they are deleted.
- **Command line** (on the server): `paperus export --user NAME OUT.zip`,
  with `--format zotero|jabref|mendeley`, `--owner NAME` (repeatable:
  "Me" or a group's name or path),
  `--collection ID`, `--no-files`, `--no-notes`, `--no-tags`,
  `--no-collections`, `--no-references`, `--no-archive`, `--trash`. `OUT`
  is the first zip; further parts are written beside it
  (`OUT-part2-of-3.zip`).
- **What it holds**: exactly what the person can read when it is written
  (their own library and their groups'); other people's private papers,
  notes, tags and collections never appear. Everything comes from one
  consistent snapshot of the database.
- **API** (session only, not with access tokens, like imports):
  `POST /api/exports/estimate`, `POST /api/exports`, `GET /api/exports`,
  `GET /api/exports/{id}`, `GET /api/exports/{id}/parts/{n}` (answers range
  requests), `DELETE /api/exports/{id}`.

## The zips

```
paperus-export-2026-11-07-1530/
  library.sqlite   paperus' tables, only the rows the person can see
  part.json        which export and part this zip is
  README.txt       what is where, in plain words
  files/           each file once: "<first author> <year> - <short title>.pdf"
```

- **Parts**: a zip is at most 2 GB (`export.PART_LIMIT`). Part 1 holds
  `library.sqlite` (its first entry), `part.json`, `README.txt` and files
  until the limit; later parts hold `part.json` and files, under the same
  top folder, so unpacking all parts into one place gives the whole export.
  Each part is an ordinary zip (not a split archive), named after the
  time of the export (UTC): `paperus-export-2026-11-07-1530-part1-of-3.zip`,
  or without the suffix if there is one. A file larger than the limit gets a zip of its own.
- **part.json**: `{"format": "paperus-export", "format_version": 1,
  "contents": "paperus", "export": "<id>", "name":
  "paperus-export-2026-11-07-1530", "part": 2, "parts": 3}` (`contents`:
  `zotero`, `jabref` or `mendeley` for the other programs).
- **Files** are stored as they are (PDFs, images, archives: no
  compression, readable in place); text-like files (text, CSV, BibTeX, …)
  and the database are compressed. Names are safe on Windows, macOS and
  Linux, at most 100 characters before the extension, unique (also where
  case does not count: "… (2).pdf"); the extension comes from the media
  type. A paper's other files carry their role: "… (supplementary).csv".
  A content used by several papers is there once.

### Only the database

`library.sqlite` is the first entry of part 1, so it can be taken out
without unpacking (or downloading) the files:

```sh
unzip paperus-export-2026-11-07-1530.zip "*/library.sqlite"
```

```python
import zipfile

with zipfile.ZipFile("paperus-export-2026-11-07-1530.zip") as z:
    z.extract("paperus-export-2026-11-07-1530/library.sqlite")
```

The download answers range requests, so tools that read a zip remotely
fetch only its directory and the database.

### Opening it

Any SQLite tool: [DB Browser for SQLite](https://sqlitebrowser.org),
[Datasette](https://datasette.io), Python's `sqlite3`, or
`sqlite3 library.sqlite .dump` for a plain SQL text. For example, each
paper with its file:

```sql
SELECT items.title, items.year, files.path
FROM items
JOIN versions ON versions.item_id = items.id
JOIN files ON files.version_id = versions.id
WHERE files.role = 'main' AND files.included = 1;
```

## The database

The tables and columns are paperus' own (see `server/src/paperus/models.py`
and [architecture](architecture.md#data-model-first-sketch)), less what is
derived or internal: text passages, vectors, OCR results, sessions,
tokens, settings, imports, change numbers, who opened what, note
histories. Types: ids (UUIDv7) and times (ISO 8601 in UTC, ending in `Z`)
as text, JSON as text, true/false as 1/0. Foreign keys and indexes are as
on the server, so joins work. Tables left out by a choice are there, empty,
so the schema stays the same.

| Table | One row per | Columns |
| --- | --- | --- |
| `paperus` | the export (one row) | `format` ("paperus-export"), `format_version` (1), `export_id`, `name` (the top folder), `parts`, `paperus_version`, `exported_at`, `exported_by` (username), `server_url` (the server's public address, if set), `options` (JSON: owners, collection, include, trash, collection_name) |
| `owners` | owner of something exported | `id` (the library's id), `kind` (`me` or `group`), `name` ("Me" or the group's path, "Uni/QCode Lab"), `role` (the exporting person's: reader, member, admin; none for "Me"), `group_id` |
| `users` | person named in another table | `id`, `username` (no emails, no passwords) |
| `items` | paper (or other work) | `id`, `created_at`, `library_id` (its owner), `type` (CSL), `title`, `year` (cached from the shown details), `file_wanted` (0: needs no file), `archived_at`, `references_source` (arxiv, crossref, pdf), `overrides` (JSON: manual edits per CSL field; null hides a field), `added_by`, `changed_at`, `deleted_at`, `deleted_by` (in the trash) |
| `versions` | edition of a paper | `id`, `created_at`, `item_id`, `kind` (draft, submitted, preprint, accepted, published, edition, other), `label` ("2nd edition"), `csl` (JSON: CSL-JSON metadata), `metadata_source` (lookup, manual, import, sync, file), `pinned` (shown and cited whatever its kind), `created_by` |
| `identifiers` | identifier of a version | `id`, `created_at`, `version_id`, `scheme` (doi, arxiv, isbn, pmid, url), `value` (normalized) |
| `files` | file of a version | `id`, `created_at`, `version_id`, `role` (main, supplementary, slides, transcript, recording, other), `filename` (as uploaded), `media_type`, `source` (upload, open_access, browser, import), `uploaded_by`, `deleted_at`, `deleted_by`, `sha256` (of the contents), `size` (bytes), `included` (1: in the zips), `path` (in the export folder: `files/…`), `part` (which zip) |
| `tags` | tag or keyword | `id`, `created_at`, `library_id` (its owner), `name`, `color`, `description` |
| `item_tags` | tag on a paper | `item_id`, `tag_id`, `source` (manual; automatic: a keyword from the paper's details; ai: suggested by an assistant), `added_by`, `created_at` |
| `collections` | collection | `id`, `created_at`, `library_id`, `name`, `description`, `parent_id` (the one it is in), `rules` (JSON, smart collections: tags_all, tags_any, tags_none, types, year_from, year_to, owners, added_days), `created_by` |
| `collection_items` | paper in a collection | `collection_id`, `item_id`, `added_by`, `created_at` |
| `notes` | note | `id`, `created_at`, `library_id`, `text` (Markdown), `title` (its first line), `created_by`, `changed_by`, `changed_at`, `text_changed_at`, `deleted_at`, `deleted_by` |
| `note_items` | paper a note is about | `note_id`, `item_id`, `page`, `added_by`, `created_at` |
| `collection_notes` | note in a collection | `collection_id`, `note_id`, `added_by`, `created_at` |
| `item_references` | entry of a paper's reference list | `item_id`, `position` (from 1), `text` (as printed), `title`, `authors` ("Smith et al."), `year`, `container` (journal), `doi`, `arxiv`, `url` |
| `favourites` | paper the exporting person starred | `user_id`, `item_id`, `created_at` |
| `pinned_collections` | collection the exporting person pinned | `user_id`, `collection_id`, `created_at` |

Which rows: papers of the chosen owners (archived ones unless left out;
the trash only if asked), with all their versions, identifiers and files;
notes of those owners; their collections and tags, and the tags on the
papers of any owner the person sees (a group's tags on their own papers,
their private tags on a group's); links only between exported rows. With
one collection: it and those inside it (it at the top), the papers in them
(of a smart collection: those matching it), the notes filed there or about
those papers, the tags on those papers.

## For other programs

The same export, with the same choices, zips, parts and file names, but
instead of `library.sqlite` part 1 starts with one file the other program
imports, written by `paperus.formats`:

| Format | File | Holds | Cannot hold |
| --- | --- | --- | --- |
| Zotero | `paperus.rdf` (Zotero RDF) | papers, files, tags and keywords (Zotero's automatic tags), collections, notes (on papers and alone) | reference lists |
| JabRef | `paperus.bib` (BibTeX) | papers, files (linked from the `.bib`), tags and keywords together, collections (as groups), notes on papers (in the comment) | reference lists, notes on no paper |
| Mendeley | `paperus.ris` (RIS; also EndNote, Citavi) | papers, files (linked, Mendeley does not take them), tags and keywords together, notes on papers | reference lists, collections, notes on no paper |

- Each paper is written with its shown version's details (with manual
  edits) and identifiers, and all its files at `files/<name>`, relative to
  the written file (unpack the zips into one folder before importing).
- **Collections** are paths of names. When several owners are exported,
  each owner's collections sit under its name: the group's own name
  ("QCode Lab/Thesis"; its whole path where two groups have the same
  name), the person's username for their own. A smart collection holds the
  papers that match it when exporting.
- `README.txt` says how to import the file into the program, and what it
  could not hold. The website greys out the choices a format cannot hold.
- Importing such a zip into paperus reads it as that program's export
  (one zip at a time), not as paperus' own.

## Importing it back

The import page takes the zips (all parts at once, in any order), and so
does `paperus import part1.zip --user NAME` (it finds the other parts
beside it; "Me" to their library, each group into a collection named
after it, or everything into `--group`; clashing names take their
defaults). See also [ingestion](ingestion.md#import-from-other-reference-managers)
and [import-mapping](import-mapping.md).

1. **Checked first**: part 1's database says how many parts there are;
   each part's `part.json` says which export it belongs to. Missing parts
   are named with how many files they hold ("Part 2 of 3 is missing
   (paperus-export-…-part2-of-3.zip): add it, or import without its 41
   files"); they can be added before starting. Zips of another export are
   left out by name. Without part 1: "Part 1 holds the database: add it".
   Exports of a newer format are refused ("update paperus here first").
2. **Where things go**: "Me" goes to the person's library; for each group
   of the export the person chooses: into a group here, create the group
   here (where they may), into their library in a collection named after
   the group (the default), or into their library without one. Then the
   tags and collections whose names clash with (or are like) those where
   they go are listed, each with a choice: merge, make new, or map to
   another. The rules, defaults and name likeness are in
   [import-mapping](import-mapping.md).
3. **Applied**, paper by paper, like other imports (a report at the end):
   - Papers already here are found, not added again: the same id (if the
     person sees it), else the same DOI, arXiv ID or other identifier, else
     a file with the same contents. Found papers get what they lack
     (versions, files, tags, collections, notes, the star), as far as the
     person may change them. Importing the same export twice adds nothing.
   - New rows keep their ids from the export where unused here, so a later
     import finds them; everything else is kept: versions with kinds,
     labels, identifiers, metadata and where it came from, the pinned one,
     manual edits, files with their roles (read again for search, as
     uploads), tags with their sources (keywords stay keywords), the
     collection tree and smart rules (their tags and owners those here),
     notes with their links and pages, favourites, archive marks, the trash,
     reference lists, times. People named in the export are the same here
     only if a person with the same id and username exists; otherwise the
     importing person.
   - Each file is checked against its SHA-256: a damaged or cut-off file is
     reported by name and left out, the rest comes in. Contents already in
     the store are taken from there only if the person already sees a file
     with them (a SHA-256 alone gives no one a file). Files not in the
     export (left out, or in a part not uploaded) are reported as missing;
     Manage → Missing can fetch them later.
- **Untrusted zips**: nothing is unpacked under its own name (the database
  goes to a temporary file of paperus' own and is opened read-only); paths
  in the database only look up zip members; sizes are checked first (the
  database at most 8 GB, files at most the upload limit); every value is
  checked before use; a row that cannot be read is reported and skipped.

## Where exports are kept

On the server, in `exports/` beside the stored files (`PAPERUS_EXPORT_PATH`
to change it; in the container `/data/files/exports`), one folder per
export. This is on the disk that holds the library anyway, and outside the
file store: the store keeps its contents in `blobs/`, which is all that
integrity checks, storage figures and backups with files look at (backups
take the files the database lists). Exports are deleted after a day (an
hourly job), and their rows a week later; leftovers of interrupted exports
go with them. They are written by the worker in the import queue, one at a
time per person; memory stays the same whatever the library's size (rows
go to SQLite a few hundred at a time, files are copied in chunks).
