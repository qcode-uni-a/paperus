# The demo

The website as it is, on the homepage (`site/`, GitHub Pages) at
`/paperus/demo/`, with a recorded library instead of a server: anyone can
look around without installing anything. A banner on every page says
what it cannot do: uploads, changes (they are refused) and search by
meaning; search finds single words.

## How it works

- **The website** is built once more with `VITE_PAPERUS_DEMO=1`, below the
  demo's path (`PAPERUS_WEB_BASE`, see `web/vite.config.ts`). Before it
  starts, it registers its service worker (`web/src/hooks.client.ts`).
- **The service worker** (`web/demo/service-worker.js`) answers every call
  to `/api/` from the recording, and serves the website's entry for its
  pages. Calls that change something get 403 with a short explanation.
- **The recording** (`record.ts`, as a Playwright test): a fresh paperus
  (the e2e tests' server) gets the demo library (`seed.ts`); the website,
  as Mira, visits every page it can reach, on a computer and on a phone
  (fluent mode), and each answer from the API is kept. Then a search for
  every word in the library, by words (the server runs without the ML
  service, as in the e2e tests). Server addresses in the answers become
  `https://paperus.example.org`.

`npm run demo` in `e2e/` (`scripts/demo.sh`) does all of it into
`site/demo/` (not checked in); the homepage's workflow does the same
before it publishes. To look at it here, serve a folder that has `site/`
as `paperus/`, then open `/paperus/demo/`.

## What is in the library

Only what may be published:

- **Classic papers with their full text**: public-domain scans from
  Wikimedia Commons (`papers.json`: Maxwell 1865, Planck 1901, Einstein's
  dissertation of 1905 and his 1907 paper on specific heat), with the text
  layer the scans carry. Not checked in: `fetch.ts` downloads them when the
  demo is recorded (the homepage's workflow caches them), and checks each
  file first: Commons still marks it public domain, and its SHA-1 is the
  one listed. A note in the library names each one's source. `words.py`
  picks their words worth searching for (four letters or more, in two
  passages at least).
- **Classic papers, details only**: titles, authors, years and journals of
  well-known papers (Einstein, Rutherford, Bohr, Noether, Heisenberg,
  Dirac, Shannon, Bell, Feynman), bibliographic facts as in any
  reference list. Not their text or their PDFs: each has a one-page PDF
  made here (`fixtures/pdf.ts`) that says so.
- **Written for the demo**, under paperus' licence (Apache-2.0): the
  lecture notes `oscillator.tex` (two columns, equations, a figure;
  typeset by `pdfs.sh`), the seminar note, the tags and collections.
- **Made up**: Mira Kessler, her Theory group and her course.

The homepage's own example quotes Maxwell (1865), in the public domain.
