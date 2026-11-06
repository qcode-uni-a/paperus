# paperus browser extension

One click on the paperus button saves the paper you are reading to your
paperus library, with its PDF. On arXiv, a small button next to each paper
does the same; a full one with a check means you have it already.

- The PDF is downloaded in your browser, with your own access (campus
  network, publisher login), and sent to paperus; one paperus has already
  (same SHA-256) is not sent again.
- Details come from the paper's DOI (arXiv papers have one too), else from
  the page (Highwire/Google Scholar `citation_*` tags, Dublin Core).
- The extension may only add papers and see which ones you have: it gets a
  token with `papers.read`, `papers.write` and `groups.read` (for choosing
  the owner). End it in paperus under Settings → Access tokens.

## Install (until it is in the stores)

Download `paperus-chrome-….zip` or `paperus-firefox-….zip` from the GitHub
release, or build it (below).

- **Chrome, Edge, Brave**: unzip; open `chrome://extensions`, switch on
  Developer mode, "Load unpacked", choose the folder.
- **Firefox** (140 or later; on Android 142): open `about:debugging#/runtime/this-firefox`,
  "Load Temporary Add-on…", choose the zip (until Firefox restarts; a signed
  version comes with the store).

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

`src/background.ts` handles the button and the calls to paperus,
`src/page.ts` runs inside the web page (details, PDF, the note),
`src/arxiv.ts` puts the buttons on arXiv, `src/options.*` is the settings
page. For automated tests, `PAPERUS_EXTENSION_TEST_HOST="http://localhost/*"`
allows a paperus address up front (a robot cannot answer the permission
prompt).
