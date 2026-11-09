# paperus browser extension

One click on the paperus button saves the paper you are reading to your
paperus library, with its PDF. On arXiv, a small button next to each paper
does the same; a full one with a check means you have it already.

- **An open PDF** is saved as it is; paperus reads its details from the
  file (a DOI or arXiv ID in it). Firefox's PDF viewer lets no extension
  in, so there the extension fetches the PDF itself: Firefox asks once per
  website for that.
- **Another owner** (a group): right-click the button, "Save to …". A plain
  click saves to the owner chosen in the settings.
- **The settings** (address, owner): right-click the button, "paperus
  settings".
- **When saving fails**, the page says why; where it cannot (a browser's own
  PDF viewer), a small window does, with "Allow and save" if the extension
  first needs access to the PDF's site.
- **Many PDFs at once**: paperus' Manage → Missing page asks the extension
  to get the PDFs of papers it lacks: each opened at its publisher in a
  background tab, its PDF saved into the paper. The first time, a small
  window asks for access to publisher sites (the browser's prompt). Open
  copies whose sites refused paperus' server are fetched first. A
  paper that fails says why: a check for robots (a captcha), no access (a
  login or paywall), or no PDF on the page. The result shows in paperus.

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
`src/allow.*` asks for access to publisher sites, `src/options.*` is the
settings page. For automated tests, `PAPERUS_EXTENSION_TEST_HOST="http://localhost/*"`
allows a paperus address up front (a robot cannot answer the permission
prompt) and lets extension pages ask for a save by message (`testSave`,
with a tab ID), as a robot cannot click the button either.
