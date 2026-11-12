# paperus browser extension

One click on the paperus button saves the paper you are reading to your
paperus library, with its PDF. On arXiv, a small button next to each paper
does the same; a full one with a check means you have it already.

- **The popup**: a click on the button opens a small window under it (as
  Zotero's does) and saves at once, to the owner chosen in the settings:
  it shows each step, then the paper, its PDF or why not, and a link to it
  in paperus. A paper just added moves to another owner (a group) by
  choosing it there. A paper paperus has already, with its PDF, is not
  saved again: the popup says so and offers its supplementary files that
  are not in paperus yet ("Add to this paper"), and "Save again" to fetch
  it all anyway.
- **On arXiv and Google Scholar**: a small button next to each paper; a
  full one with a check means you have it, a click on a dimmed one saves
  it (on Scholar from its page, opened out of sight, with its PDF).
- **An open PDF** is saved as it is; paperus reads its details from the
  file (a DOI or arXiv ID in it). Firefox's PDF viewer lets no extension
  in, so there the extension fetches the PDF itself; if the site answers
  that with a web page (a check for robots, a login), it opens the PDF
  again in a tab out of sight, as your own visit, and keeps a copy of what
  Firefox receives (the reason for its `webRequest` permissions, Firefox
  only).
- **Supplementary material, code and data** come along: the supplementary
  files the article links (Nature's, Elsevier's, Wiley's, ACS's, APS's,
  arXiv's ancillary files, …; up to 10, 100 MB each) are saved with the
  paper, listed in the popup under it with how each went (never as papers
  of their own), and links to its code and data (GitHub, Zenodo, Figshare, …,
  where the article says they are its own: in its abstract, a "Code
  availability" section, "the data are available at …") are shown on its
  page. Not the references' links, nor the site's own.
- **Pages that list papers or files** (a course's lecture notes, a
  publication list, a journal's contents): the popup lists the files the
  page links (PDFs, slides, …) and the papers it links by DOI or arXiv ID,
  marks those in paperus, and saves the ticked ones, each as a paper of its
  own. Files over 100 MB are left out until you click "Save anyway". On a
  paper's own page, "… more papers and files linked here" opens the same
  list.
- **Someone's Google Scholar profile**: the popup lists all their papers
  (Scholar's further pages read too, at most 1,000), marks those you have
  (by title), and adds the ticked ones: by arXiv ID where Scholar names
  one, else by title, with the DOI paperus finds at Crossref (same title,
  first author and year), else as listed.
- **Papers you have, on the button**: when a paper's page (or its PDF)
  opens, the button shows a green check if the paper is in paperus with
  the PDF of the version the page shows (journal or preprint), an orange
  "!" if that PDF is missing (a click saves it); its tooltip names the
  paper, and another version's PDF if there is one. Only the page's DOI or arXiv ID is looked up;
  the settings turn it off.
- **Another owner** at once: right-click the button, "Save to …".
- **The settings** (address, owner, the version installed): "Settings" in
  the popup, or right-click the button, "paperus settings".
- **When saving fails**, the popup says why; with "Allow paperus on all
  websites" if that access was taken back (Firefox lets one).
- **Many PDFs at once**: paperus' Manage → Missing page asks the extension
  to get the PDFs of papers it lacks: each opened at its publisher in a
  background tab, its PDF saved into the paper. Open copies whose sites
  refused paperus' server are fetched first. A paper stopped by a check
  for robots is tried again at the end in a tab in front, where such a
  check often passes by itself (or you answer it); paperus waits up to
  three minutes, then saves the PDF and closes the tab. A paper that fails
  says why: a check for robots (a captcha), no access (a login or
  paywall), or no PDF on the page. The result shows in paperus.
- **A paper's page in paperus** offers "Get the PDF with the extension"
  for a version without one, the same way.
- **Tabs out of sight**: the tabs the extension opens for its work (Missing,
  Scholar's buttons, PDF links that lead through other pages) are hidden
  from the tab bar in Firefox (its `tabHide` permission; Firefox says once
  that an extension hides tabs) and, in Chrome, which cannot hide tabs, open
  in a minimised window of their own.

- **Access to websites** is asked for once, when installing (as Zotero's
  extension does): to read the page you click on, fetch its PDF (also where
  a publisher sends it on to another site, as ScienceDirect does), reach
  your paperus, and get PDFs for Manage → Missing. It is used only then,
  and to read a page's DOI or arXiv ID when it opens (to mark a paper you
  have; can be turned off).
- The PDF is downloaded in your browser, with your own access (campus
  network, publisher login), and sent to paperus; one paperus has already
  (same SHA-256) is not sent again.
- Details come from the paper's DOI (arXiv papers have one too), else from
  the page (Highwire/Google Scholar `citation_*` tags, Dublin Core).
- The extension may only add papers and see which ones you have: it gets a
  token with `papers.read`, `papers.write` and `groups.read` (for choosing
  the owner). End it in paperus under Settings → Access tokens.

## Install

- **Firefox** (140 or later; on Android 142): from
  [addons.mozilla.org](https://addons.mozilla.org/firefox/addon/paperus/).
- **Chrome, Edge, Brave** (until it is in the Chrome Web Store): download
  `paperus-chrome-….zip` from the GitHub release (or build it, below),
  unzip; open `chrome://extensions`, switch on Developer mode, "Load
  unpacked", choose the folder.

Then open the extension's settings (it opens by itself on the first click),
enter your paperus address and click Connect; confirm in the paperus tab.
Choose who new papers belong to.

## Develop

Checking it on publishers' sites (articles, steps and a table to fill in):
[`publisher-check/`](publisher-check/README.md).

```sh
npm ci
npm run check   # TypeScript
npm run build   # dist/chrome, dist/firefox and their zips
```

Building needs Node.js (22 or later; CI uses 26) and `python3` (for the
zips). The output is not minified: `dist/firefox` is what is handed in at
addons.mozilla.org, `npm run source` packs the source (what git has) for
the review. What it sends and keeps: `PRIVACY.md`.

`src/background.ts` handles the button, the calls to paperus and getting
PDFs for Manage → Missing, `src/page.ts` runs inside the web page
(details, PDF, the note, what a page shows), `src/causes.ts` tells why a
page gave no PDF, `src/arxiv.ts` puts the buttons on arXiv, `src/site.ts`
runs on the connected paperus (marks the page, passes requests on),
`src/popup.*` is the popup under the button, `src/allow.*` asks again for
access to websites (taken back in Firefox), `src/options.*` is the
settings page. For automated tests, `PAPERUS_EXTENSION_TEST_HOST="http://localhost/*"`
allows a paperus address up front (a robot cannot answer the permission
prompt) and lets extension pages ask for a save by message (`testSave`,
with a tab ID), as a robot cannot click the button either.
