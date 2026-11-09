# Changelog

## Unreleased

- **Search finds papers by their title and abstract**, with or without a
  file; a match of the searched words in a title or abstract ranks higher
  than one in some text (`item_chunks`, added to the one migration). On
  the evaluation questions: the right paper first 68% of the time (was
  66%), among the first five 93% (was 89%).
- **Administrator setup**: a last step to create a group (or skip it).
- **Browser extension**: its icon outlined and filling its square, easier to
  see on light and dark toolbars.

## 0.0.17 (2026-11-09)

- **Database**: the one migration (`0001`) gained `items.abstract`, the
  tables `annotations` and `annotation_shares`, and `files.file_marks`. An
  installation of 0.0.16 (none exist besides the developer's) adds them as
  in that migration.
- **Firefox add-on**: public on addons.mozilla.org; each release hands its
  version in from now on.
- **Browser extension**: connects in Firefox also to a paperus at an
  address with a port (paperus answers the browser's preflight from
  extensions; the extension asks for the host, any port); where a page
  cannot show why saving failed (Firefox's PDF viewer), a small window
  does, with "Allow and save" when access to the PDF's site is missing;
  "paperus settings" in the button's right-click menu; on arXiv's lists
  the button stands after "[pdf, html, other]", so its label moves nothing.

- **Annotations in the PDF viewer** (see [annotations](docs/annotations.md)):
  highlights, underlines and strike-throughs (select text, then a colour),
  sticky notes, words on the page, areas around figures, and the pen with
  an eraser, each with a colour (Zotero's eight), a comment and tags; a
  list by page to find them and gather them into a note; on a phone the
  tools sit behind a round button and two fingers scroll. Each person's
  own; "Show mine to the group" shares one's annotations of a paper.
- **A PDF's own annotations become paperus's**: highlights, notes, words
  and pen strokes made in another reader are taken in once when the file
  is read (as the uploader's: editable, searchable in the list), and the
  page is drawn without their painted copies; other annotations of the PDF
  stay as they are.
- **Annotations travel**: "Download with annotations" gives the PDF with
  them written in as standard PDF annotations (any reader shows them); the
  paperus export carries them (and importing it brings them back);
  assistants read them with `get_annotations`.
- **Fluent mode** (the viewer's toggle; on by itself for two-column papers
  on a phone): the pages cut into pieces in reading order, one column
  across the screen, the columns running on into each other, without
  margins, running headers and footers; figures stay whole, a part across
  the page keeps only its own ink, and a faint line names what follows a
  break ("Right column", "Page 3"). Selecting, highlighting (also over a
  column break), notes and the pen work as on the page (see
  [annotations](docs/annotations.md)). The contents also jump to headings
  in the right column, and read bookmarks that mark a rectangle (`FitR`).
  Tested on layout twins of 70 pages of 40 journals, theses and books
  (their measured layout, no content; `npm run test:layout`).
- **Sharp when zoomed by pinching**: the PDF pages on screen are drawn
  again at the zoom once it settles, instead of blurring as an enlarged
  picture (pages away from the screen go back to the usual sharpness).
- **Abstracts**: shown (folded) on a paper's page. A paper whose details
  have none gets OpenAlex's (asked anyway for its authors), else the
  paragraph after the "Abstract" heading of its PDF; its details' own,
  and one removed by hand, always win (`items.abstract`, added to the one
  migration).

## 0.0.16 (2026-11-09)

- **Database**: the one migration (`0001`) gained the columns
  `users.display_name`, `users.orcid`, `users.name_format` and
  `author_changes.renamed_from`. An installation of 0.0.15 (none exist
  besides the developer's) adds them as in that migration.
- **Open-access PDFs from every open copy**: the server tries all the open
  copies OpenAlex and Unpaywall list (arXiv first, then repositories such
  as a university's, the publisher last), not only Unpaywall's best one;
  OpenAlex is asked without a contact email too. Copies whose sites
  refuse the server (publishers often do) are handed to the browser
  extension from Manage → Missing, which fetches them first.
- **A paper's journal and year** are a row of their own on its page, like
  its tags and collections (no longer in brackets after the authors).
- **PDF contents**: page numbers always at the right edge.
- **Add someone's papers**: an author's page with an ORCID iD or OpenAlex
  id lists their papers at OpenAlex ("Add their papers…"); those not in
  the library can be chosen and added by DOI, all at once. A paper's
  copies (arXiv, SSRN, repositories) are one entry, under the journal's
  DOI. Manage → Missing does the same for one's own papers, by one's ORCID
  iD (Settings → Account).
- **Imports find missing DOIs by title**: a paper without a DOI or arXiv
  ID gets one from Crossref when the title, first author and year agree,
  so its authors, open-access copy and references are found too.
- **Authors under their fullest name**: a person is shown with given names
  written out when one of their papers has them ("Michel Pioro-Ladrière",
  not "M. Pioro-Ladrière"), and found by any spelling on their papers.
- **Settings in sections**, like the administration's: Account (a display
  name others see instead of the username, the profile picture, one's
  ORCID iD), Login, New papers, Appearance (theme and names), Access
  tokens and apps, Export; the open ones are in the address. With an
  ORCID iD, one's own author page says "This is you", and Manage → Authors
  lists oneself first.
- **Duplicate review previews saved web pages** (and images), not only
  PDFs: a paper whose only file is a snapshot no longer shows "No PDF".
- **Names written one way**: people's full names are written family name
  first ("Benito, Mónica") everywhere on the website; Settings → Names
  switches to given name first ("Mónica Benito"), for all one's devices.
  Manage → Authors sorted by name follows the choice.
- **Authors compared before merging**: "Probably the same" pairs (one by
  one, or each with "Compare…") and "The same person" on an author's page
  show both people side by side: their papers, where they were, their
  co-authors, with what both have in green (dashed: probably the same,
  written differently). Undoing a merge also gives the old name back.
- **The trash says when it is emptied**: how many days things stay
  (Administration → Settings → Trash), and on each paper and note the day
  it is deleted for good; or that the trash stays until emptied by hand.

## 0.0.15 (2026-11-08)

- **Authors as people** (#35, first part): each paper's authors are linked
  to people (the same ORCID or OpenAlex id, else the same full name; a
  name several people share goes to the one with the same co-authors, or
  is listed to check). Authors in lists and on a paper's page lead to the
  author's page: their papers in your library, who they wrote with, where
  they were, others of the same name. Papers by someone else of the same
  name are split off there and kept apart from then on; two records of
  one person are merged. Manage → Authors lists them, with the authors to
  check. OpenAlex gives each author's id, ORCID iD and affiliation on
  each paper with a DOI (an hourly job; Administration → Settings →
  Server → Authors), so namesakes are told apart and an author's page
  shows where they were. Manage → Authors also suggests people who are
  probably one ("M. Benito" and "Mónica Benito", co-authors in common
  first): the same person, or different people. See docs/authors.md.
- **Smart collections by author**: "By these authors" among the rules (an
  author's page offers "Smart collection" with them filled in); the
  library's filter takes them too, and saves them.
- **Exports keep who is who**: paperus exports carry the authors as
  people and each paper's links to them ("Authors as people", ticked at
  first; `--no-authors`); importing finds the people here by ORCID iD,
  OpenAlex id or name, keeps splits and links made by hand, and maps
  smart collections' author rules. Older exports still import.
- **AI assistants and authors**: `find_authors`, `get_author`, papers by
  an author with `list_documents(author_id=…)`, and each author's person
  in `get_document`.
- **Papers Zotero kept as web pages**: when Zotero could not get a
  paper's PDF it saved the journal's page instead, titled like the page
  or by its address. A Zotero import now reads the DOI in such an address
  (`journals.aps.org/prb/pdf/10.1103/…`) and looks up the paper's
  details, so the page comes in as the paper (or joins the one already
  in the library), and its open-access copy is looked for.
- **The database migrations are one again** (`0001`), with this release's
  changes in it. An installation of 0.0.14 (none exist besides the
  developer's) needs the table `author_changes` and the column
  `users.handed_over` added as in that migration, then, once:
  `UPDATE alembic_version SET version_num = '0001';`
- **Fixing authors needs the right to change their papers**, since author
  records are shared by everyone: splitting, merging and "different
  people" need a paper of each person that is yours to change (a reader
  in a group can no longer change who is who for the whole group). Every
  fix is kept, listed on the author's page ("Changed by hand"), and can
  be undone.
- **Privacy fixes** (a review of every route and assistant tool, now also
  a test that tries them all as someone else):
  - an access token needs "read files" for a file's passages, not only
    "read papers";
  - filtering papers or notes by someone else's tag or collection is
    refused (it would show what they tagged or filed);
  - tagging or filing a group's paper (privately) no longer moves it up
    in the others' recent papers;
  - a reader's private upload of a group's paper stays private (it joined
    the group's paper before);
  - the readable copy's preview shows the administrator's own papers;
  - "To check" offers only people one sees, and the change log on an
    author's page does not name people one does not see.
- **Hand-over**: an administrator can no longer hand someone's library to
  themselves; the person learns, when back, where their papers went and
  who handed them over.
- Manage → Authors shows in the menu how many authors there are to check
  and pairs that are probably one person.

## 0.0.14 (2026-11-07)

- **Phones and tablets**: on tablets held upright (up to 900 px) the menu
  is a drawer, so lists and tables get the whole width (Manage → Tags and
  Administration → Users ran off the screen); page headings put their
  buttons below the text when it needs the room; long tag names wrap
  into a soft box; the search field says "Search the library" (the
  longer text was cut off); the hints of Settings → Export are spaced
  from their labels again. Administration → Settings shows its forms once
  the saved settings are there (a choice made earlier was undone).
- **Filter the library**: a Filter button beside the number of papers
  opens the rules of smart collections (with all, any or none of some
  tags or keywords, types, publication dates, owners, recently added);
  what is filtered by is said in a sentence above the list, with "Clear
  filter" and "Save as smart collection". Tags in the list and authors
  (in the list and on a paper's page) are links to their papers; on
  Manage → Tags, the number of papers is. The filter lives in the
  address, so Back and shared links keep it. The list API takes the same
  rules and `author` ("Family, Given": the family name and first letter).
- **A paper's journal** is on its own line below the authors.
- **Back to a list** finds its place by the paper that was at the top of
  the window, so papers added meanwhile do not move it.
- **Why no open copy was found**, in plain words with what to do: after
  "Download all open-access copies", the papers without one are listed
  with the reason (no open copy known, the site refused, a login page
  instead of the PDF, …), and each paper on Manage → Missing says it in
  red. Without a contact email, it says that Unpaywall is not asked.
  AI assistants get the same reasons.
- **Reading a paper**: no search bar at the top; the bar with the page
  number sticks fully below the header (it was partly hidden) and stays
  one line, a long chapter name cut short with "…". "Open file" is an
  icon; phones have no zoom buttons (they zoom by pinching). Long chapter
  names wrap inside the contents instead of running off the screen.
- **Back keeps your place**: going back from a paper to the library, a
  collection, Recent, Favourites or the Archive returns to where you were
  in the list, with as many papers loaded as before, instead of the top.
- **Keywords folded** on a paper's page ("Keywords (n)", below the
  collections), like Similar papers and References: there when wanted,
  out of the way of the paper's own tags.
- **AI assistants can do all of Manage → Missing**: besides listing and
  downloading one paper, download all of a section in the background and
  follow its progress, and list the papers marked as needing no file.
  Only "Get with the extension" stays with the person (it uses their
  browser and access).
- **AI assistants handle files in general**: `list_files` (by media type,
  next to a PDF, or in the trash), `trash_files` and `restore_files`, for
  whatever needs tidying, e.g. saved web pages next to a PDF
  (`library_checkup` counts those).
- **Download all open-access copies** (Manage → Missing) shows its
  progress: how many papers were tried and found, with a bar; found ones
  fold away, a message sums up at the end, and if nothing moves for a
  minute it says so (the worker may not be running).
- **Dates and times** in one form for everyone (Administration → Settings
  → Server): as each browser is set (as before), Europe (31.12.2026,
  14:30), UK (31/12/2026), ISO 8601 (2026-12-31) or US (12/31/2026,
  2:30 PM). Lists, schedules and smart collections' descriptions follow
  it, and date fields take dates typed that way ("15.3.2024"), with a
  calendar beside them.
- **Saved web pages** (Zotero's snapshots) show on a paper's page as
  pages, not as their source text, in a frame that runs no scripts and
  loads nothing from the web (also when opened on their own, so no
  publisher learns about it). Manage → Missing offers to move the web
  pages that sit next to a PDF to the trash (from imports before 0.0.10).
- Fixed: adding a file whose content paperus already had, while the
  worker was still reading the first one, could fail with a server error
  (two locks taken in opposite order).
- **Smart collections by dates**: "Published from … to …" with date
  pickers; a paper counts by the days its date stands for (a day, a month,
  a year), so "March 2024" papers are in a 1–31 March collection and a
  "2024" paper in any range touching 2024. Older year rules keep working.
  The new-collection dialog fits a phone's screen again.
- The contents of a PDF open unfolded; fold chapters by hand.
- **Export everything you can see** (Settings → Export): your papers and
  your groups' (each marked with its owner), with their versions, files,
  notes, tags and keywords, collections, reference lists, stars and the
  archive, as one SQLite database (open it with any SQLite tool) and a
  folder of the files with readable names, in a zip to download for a
  day. Choose whose papers and what comes along, or only one collection
  (also from a collection's menu); the size is shown first. Large
  exports come in zips of at most 2 GB. Or export for Zotero, JabRef or
  Mendeley: their file (RDF, BibTeX, RIS) with the files beside it. On the
  server: `paperus export --user NAME library.zip`.
- **Import a paperus export** on the import page (all its zips at once):
  for each group in it, choose a group here, create the group (if you
  may), or keep its papers in your library in a collection named after it
  (the default; give that collection to the group later to move them).
  Tags and collections whose names are already there (or nearly: "ToRead"
  and "to read") are merged unless you choose otherwise; similar ones are
  suggested. Nothing is lost, papers you have already are found, and
  importing it again adds nothing.

## 0.0.13 (2026-11-07)

Papers show their reference lists and what in the library cites them,
the references of any arXiv paper can be imported, the PDF viewer has a
table of contents, keywords stay apart from tags, and a new server walks
its administrator through the first steps (backups now run daily from the
start). Test coverage is above 99%, with end-to-end tests in a browser.

- **Reference lists**: each paper's page lists its references, found by
  themselves in the background: from arXiv's LaTeX source for arXiv
  papers, else from Crossref by the DOI, else read from the PDF. References
  that are in your library link to them; others have their DOI or arXiv
  link and an Import button (or Import all, into a collection named after
  the paper); text-only ones a Find button that looks them up on Crossref.
  "Cited by" shows which papers in your library cite the one you are
  reading. AI assistants read both (`get_references`, `cited_by`). Switch
  under Administration → Settings → Server. References a publisher
  deposited as bare DOIs get their title, authors and journal from
  OpenAlex.
- **Import the references of a paper**: give an arXiv ID or link on the
  import page, or upload an arXiv source (`.tar.gz`), a zip of a LaTeX
  project or a `.bbl` file. The references come into a collection named
  after the paper, with their details looked up by DOI or arXiv ID (or
  found on Crossref when certain); those that could not be recognised are
  listed in the import's report.
- **Contents of a PDF** in the viewer: a Contents button names the chapter
  being read and opens the chapters, foldable, from the PDF's bookmarks or
  else its headings; a click jumps there.
- **Keywords kept apart from tags**: what came with a paper's details
  (Zotero's automatic tags such as arXiv categories and publishers'
  subjects; Mendeley's author keywords) is imported as the paper's
  keywords: on a line of their own on its page (+ makes one a tag), not in
  the tag list or the library's rows unless asked for, and removable all
  at once under Manage → Tags. Import the same Zotero export again to sort
  the tags of an earlier import. AI assistants see which are keywords.
- **Getting started** on the library page: the first steps, each ticked
  off once done (a paper added, a library imported, the browser extension
  connected, an AI assistant connected), and for administrators what the
  server still needs (backups on, a contact email, the machine learning
  service answering, other people). Hide it any time.
- **GPU check** for administrators: Getting started (and Administration →
  Settings → Machine learning) names the GPU the ML service runs on, or,
  on the CPU, whether the machine has a suitable NVIDIA card and what to
  do: switch to the `-cuda` image, pass the GPU to its container, or
  install or update the driver (580 or newer; RTX 20xx generation on).
- **The ML service on another machine**, e.g. a workstation with a GPU
  while paperus stays on a small server: `ML_URLS` in `.env` (documented
  under docs/operations.md, "On another machine"). On the CPU, Getting
  started and the machine learning settings point there.
- **Daily backups from the start**: a new server (or one where backups were
  never set up) backs up its database every night at 03:00 UTC and keeps
  the newest 7; the files (PDFs) are added under Administration → Backups.
- **Logging in over plain HTTP** with the default HTTPS-only login cookie
  now says so (and what to change), instead of returning to the login
  page without a word.
- **Postgres gets 1 GB of shared memory** (`shm_size` in compose; Docker
  gives 64 MB): enough for parallel queries and for building a vector
  index in parallel later. Only used while needed; takes effect when the
  database container is recreated (`docker compose up -d`).
- BibTeX files that start with an Emacs-style `@Comment` line (no braces)
  are read again; they failed before.
- **Fixes:** a Zotero export whose collections contain each other no
  longer stops the import (and sub-collections of two collections with
  the same name are kept); BibTeX entries with an odd month are no longer
  dropped; AI assistants are told why a tool was refused (a reader adding
  a note, an unknown collection) instead of a bare error; collection
  pages no longer send a failing request when opened; a cut-off WebP
  picture is refused as avatar; a failing reranker address is tried last,
  like the others.
- **Tests:** end-to-end tests in a real browser (`e2e/`: setup, login,
  upload and reading, search, tags, collections, trash, archive, tokens,
  connecting an app, sharing in a group, phone layout), and test coverage
  of the server and ML service up from 91% and 75% to over 99%.

## 0.0.12 (2026-11-07)

AI assistants on the web connect by signing in (claude.ai, ChatGPT),
preprints find their published versions, papers can be archived, and a
paper's page shows the papers most like it.

- **Connect claude.ai, ChatGPT and other connectors** with OAuth: add
  `https://<server>/mcp` as a custom connector, log in to paperus and
  allow what it may do (reading only unless you tick changes). Settings →
  Connected apps lists them and disconnects them. Tokens last an hour and
  renew themselves; paperus follows the MCP authorization specification
  (dynamic client registration, PKCE).
- **Published versions of preprints**, found by themselves: every hour a
  few dozen preprints are looked up at arXiv (the DOI the authors entered)
  and OpenAlex; a published version found is added (only if its title
  matches) and from then on shown and cited. On a physicist's library,
  55 of 130 preprints got theirs. Administration → Server → Published
  versions (on by default); Jobs → "Look for published versions" starts
  it at once. With open-access copies on, the journal's PDF is tried too.
- **Archive**: papers kept for good, but left out of the library, search
  and Manage (a paper's menu → Archive; for everyone who sees it, like
  the trash). Manage → Archive lists them; search can include them
  ("Include archived papers" in the search options). AI assistants:
  `archive_papers`, and `archived` for `search` and `list_documents`.
- **Similar papers**: a paper's page lists the papers closest to it in
  meaning (by their full text), under "Similar papers"; AI assistants
  get the same with `find_similar`.
- Formulas in titles from Crossref (MathML) are kept as LaTeX (`$g$`)
  and typeset, instead of markup in the title.
- A paper's page shows its image file (a photographed note, a scan),
  not only its text.

## 0.0.11 (2026-11-07)

Search finds more: scanned pages are read (OCR), a reranker puts the best
hits first, and the ML service runs on NVIDIA GPUs. Papers without PDFs
get them (open copies by the server, the rest with the browser
extension), smart collections fill themselves, and AI assistants can tidy
the library.

- **Tidying with AI assistants** (MCP): the Manage pages as tools.
  `library_checkup` says what needs looking at; duplicates (list, merge,
  keep apart), papers without details (list with the beginning of their
  text, set a DOI), unreadable files (read again, fresh open copy),
  missing PDFs (list, download an open copy, mark as not needed), tags
  (take off, rename, merge two into one), collections (create, add,
  remove), the trash (list, restore). Each needs the matching token
  scope; the instructions tell the assistant to ask before changing
  anything. Groups and emptying the trash stay with people.
- **Manage → Missing**: papers without a PDF ("No file"), and published
  papers with only their preprint's ("Only the preprint"). Per paper:
  download an open copy (the journal's own if open access, else the arXiv
  version, which paperus finds by the DOI via OpenAlex and adds as the
  paper's preprint version), open it at the publisher to save the PDF with
  the browser extension (it lands in this paper), upload a file, or mark
  it as needing no (further) file. "Download all open-access copies" works
  through a section in the background. The menu shows how many.
- **Getting PDFs with the browser extension** (Manage → Missing): with the
  extension installed and connected, "Get with the extension" (one paper)
  and "Get all with the extension" (a section) open each paper at its
  publisher in a background tab and save its PDF with your own access; a
  notice says how many were saved and why the others were not (a robot
  check, no access, no PDF), each paper shows its reason. The first time,
  the extension asks once for access to publisher sites. Without the
  extension the page says how to get it. The one-click save also says
  when a publisher showed a robot check or a login instead of the PDF.
  Papers that get their PDF show "PDF saved" for a moment, then are packed
  up and leave the list (as each one is done, also while the extension
  works through many).
- Administration → Server → Contact email says that Unpaywall answers only
  with one.
- **Open-access copies by themselves** (Administration → Settings →
  Server, off by default): papers added without a file, also by the
  extension, AI assistants or an import, get an open copy in the
  background, a few hundred every ten minutes.
- **Formulas in titles**: LaTeX in paper titles (as APS writes them,
  `$\ensuremath{\nu}=1/3$`) is typeset with KaTeX, and Crossref's `<i>`,
  `<sub>`, `<sup>` show as such, wherever titles are shown.
- On phones, the library no longer grows wider than the screen when a
  title holds a long formula or address (also in the notes list).
- **Smart collections** (#23): a collection that finds its papers by
  rules instead of papers added to it: with all, any or none of some tags,
  of some types, published in some years, owned by someone, added in the
  last days. "New collection" → Smart; the collection page says its rules
  in words. Lists, exports, AI assistants and the menu's counts use the
  matching papers; a group's smart collection holds only its papers.
- **OCR** (#26): scanned PDFs, scanned pages inside PDFs, and images (PNG,
  JPEG, TIFF, WebP) are read in the background by the ML service, so they
  can be searched and AI assistants can read them. Columns are read one
  after the other, also on slightly tilted scans. PP-OCRv6 (Apache-2.0,
  31 MB): on our test pages 96 % of English and all German words right,
  about 3 s per page on a CPU. Administration → Settings → Machine learning
  → Reading scans (on by default); Jobs shows what waits; each file says
  whether its scanned pages are read. The upgrade reads files without text
  and images again.
- **Browser extension**: one click saves an open PDF too (also in
  Firefox's PDF viewer, which asks once per website); paperus reads its
  details from the file. A right click on the button saves to another
  owner ("Save to Radar project"); a plain click still goes to the owner
  chosen in the settings.
- **Reranking** (#9): a reranker reorders the best 40 hits of a search,
  in the website and for AI assistants. On our test questions the right
  paper comes first 89 times in 100 instead of 66 (German questions too).
  Administration → Settings → Machine learning → Reranking: Automatic (on
  when the ML service has a GPU; about 0.6 s per search), Always, Off; the
  reranker (bge-reranker-v2-m3, gte-multilingual-reranker-base,
  ms-marco-MiniLM). If it fails, results come in the usual order.
  `paperus evaluate --rerank on|off` compares.
- **ML service on an NVIDIA GPU**: the image `paperus-ml:<version>-cuda`
  (1.7 GB download) runs the models on the GPU when the container gets one,
  else on the CPU. About 20× faster on an RTX 2080 SUPER (arctic-embed-m-v2:
  188 passages/s instead of 8). `PAPERUS_ML_DEVICE` (`auto`, `cpu`,
  `cuda`); the administration says which it uses. See docs/operations.md.
  - Vectors from the GPU's model files (fp16) are stored apart from the
    CPU's (int8) and never mixed: switching re-embeds the library, as a
    change of model does. Vectors stored so far stay valid.
- The CPU image of the ML service is smaller (539 MB instead of 793 MB
  unpacked): no download cache inside.
- **Menu**: Duplicates and Unsorted show how many wait there (unsorted
  papers and unreadable files together; the details on hover), updated
  when changing pages and every minute.
- **Duplicate review**: the comparison table shows what merging does with
  each value instead of a list below it: green on the kept paper (stays)
  and for what moves over from the other one (all its files, tags,
  collections, notes, and its version with its details), grey for what is
  there already, red for what goes to the trash with the paper.
  - **Choose what to keep**: a click on a file, tag, collection or note
    leaves it out of the merge, or removes it from the kept paper (a file
    to the trash), all in the same step as the merge
    (`POST /api/items/{id}/merge` with `leave` and `drop`).
  - **Trash the other one** (`T`): no merging, the other paper only goes
    to the trash.
  - It says when the paper will show the other one's details after
    merging (its version comes first, e.g. published before preprint).
- **Browser extension in the stores**: listed on addons.mozilla.org
  (Firefox 140 or later, and Firefox for Android 142 or later); handed in
  at the Chrome Web Store. Firefox asks at install whether it may send the
  page's address and content, which goes only to your own paperus.
- Releases hand a new version of the extension to both stores, only when
  the extension changed; each release also has its source code for
  Mozilla's review. Actions → "Check store access" tests the store keys.
- The extension is type-checked against paperus's API, and a server test
  keeps the API description (`openapi.json`) current, so a server change
  that would break the extension shows in CI.

## 0.0.10 (2026-11-06)

Tested with a real Zotero library (381 papers, 60 collections): it now
comes over complete, and what goes wrong can be seen and fixed. Plus a
browser extension to save papers in one click.

- **Browser extension** (Chrome and Firefox, `extension/`): one click saves
  the paper you are reading with its PDF (downloaded with your own access)
  to your default owner; on arXiv, a button next to each paper saves it, and
  shows which ones you have. Connected from its settings with a token that
  may only add papers. Until it is in the stores: the zips on the GitHub
  release, loaded unpacked.
- **Duplicates**: "Review one by one" shows each pair side by side (first
  page, details with differences marked) and what merging does, with
  keyboard shortcuts; clearer cards in the list ("Keep this one" ← "Merged
  into it"). The same title alone no longer counts when the first authors
  differ (two books called "Introduction to Quantum Optics").
- **Files that could not be read**: listed under Manage → Unsorted with the
  reason in plain words, and "Read again" there and on the paper's page.
  **Download again** replaces a damaged file with a fresh open-access copy
  from arXiv, or by DOI via Unpaywall (with the contact email set); only a
  whole PDF that opens is taken. Without a known source, "Upload a good
  copy" leads to the paper.
- **Jobs page**: live numbers per queue, running imports, "Read failed
  files again", and a chart per queue (two minutes, with scales and times),
  shown with the chart button in its header.
- **Zotero import**:
  - Files of the same name in a zip (arXiv snapshots are often all
    "2310.html") are no longer left out when the zip has a top folder.
  - Files on their own in Zotero (no paper around them, e.g. lecture
    notes, a thesis, scanned notes) come along as documents instead of
    being left out; one downloaded from arXiv gets its arXiv ID from the
    address Zotero kept (e.g. "2601.pdf" is 2601.01704).
  - Saved web pages (snapshots) are left out next to a PDF; alone, they
    stay and are read as text, without markup, scripts or embedded images.
  - Importing the same export again repeats nothing: papers without
    identifiers are recognised by type and title.
  - An import whose worker stopped in the middle goes on when retried.
  - Dropping the export on the import page chooses it (it used to start a
    normal upload); a dropped folder gets a note to zip it first.
- **Fixed: reading PDFs in parallel.** PDFium is not thread-safe; two files
  read at once could make the worker grow until it was killed (15 GB with
  the Zotero import), or fail on valid PDFs. PDFs are now read in helper
  processes, in parallel, each with a memory and time limit (453 files
  re-read in 95 seconds, 1.5 GB at most).
- `paperus evaluate questions.json --user <name>`: how well each search mode
  finds the paper each question means (hit@1, hit@5, MRR@10); first results
  in `docs/search.md`.
- `GET /api/items/lookup?id=arxiv:…&id=doi:…`: which of these papers one has.
- Long collection names wrap (after an underscore where possible) instead
  of running into the next one.

## 0.0.9 (2026-11-05)

Ready for the pilot's groups: sharing with a group in one step, finding the
passage you searched for, and housekeeping that keeps a server tidy.

- **Share with group…** in a paper's menu: the group gets the paper, and
  the dialog says what changes for whom. Group papers say who added them
  ("Added by ada, 3 days ago").
- **Search**:
  - Opening a result marks the passage in the PDF and scrolls to it.
  - Results show each paper's authors and year under its title (also for
    AI assistants through MCP).
  - "Note" among the types in the search options, so notes can be
    searched alone or with some types of paper.
  - The search field says what the options are set to, e.g. "Search
    preprints by meaning".
- **Lists** show a small icon when a paper has a file (PDF, text, image,
  …); a click opens the file in a new tab.
- **Profile picture editor**: move and zoom the picture in a circle, with
  previews at the sizes others see. Only the 256-pixel result leaves the
  browser; the server refuses pictures larger than 512 pixels on a side.
- **Menu**: Manage sits at the bottom of the window; Administration is only
  in the profile menu, now with icons. With the menu closed, pages take
  its room.
- **Tidying up**: the worker retries jobs whose worker stopped in the
  middle (hourly), and deletes old finished jobs and expired login
  sessions (nightly). See Job settings and docs/operations.md.
- Fixed: the search options panel was squeezed to the width of its button.
- Behind the scenes: pre-commit checks in CI, Dependabot for all
  dependencies, base images and actions; the website is built with
  Node 26 (LTS); katex 0.18.10 (0.18.11 was withdrawn).

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
