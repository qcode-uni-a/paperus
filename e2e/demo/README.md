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

- **Classic papers, details only**: titles, authors, years and journals of
  well-known papers (Maxwell, Planck, Einstein, Bohr, Noether, Dirac,
  Shannon, Bell, Feynman and others), bibliographic facts as in any
  reference list. Not their text or their PDFs: each has a one-page PDF
  made here (`fixtures/pdf.ts`) that says so.
- **Written for the demo**, under paperus' licence (Apache-2.0): the
  lecture notes `oscillator.tex` (two columns, equations, a figure;
  typeset by `pdfs.sh`), the seminar note, the tags and collections.
- **Made up**: Mira Kessler, her Theory group and her course.

The homepage's own example quotes Maxwell (1865), in the public domain.
