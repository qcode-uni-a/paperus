# End-to-end tests

A real browser (Playwright: Chromium, or WebKit) against a real paperus: the API
serving the built website, the worker, and a fresh database `paperus_e2e`
on the compose Postgres. No ML service: search falls back to keywords, as
it does when the ML service is down.

```sh
docker compose up -d                 # Postgres on localhost:5432
cd e2e
npm install
npx playwright install chromium      # once (in CI: --with-deps chromium)
npm test                             # builds web/build, then runs the tests
npm run test:quick                   # without building the website again
```

WebKit is Safari's engine, and the apps' on macOS, iOS and Linux
([apps.md](../docs/apps.md)); CI runs every test in both. One engine per
run (they share the database), chosen by `PAPERUS_E2E_BROWSER`
(`chromium`, the default, or `webkit`):

```sh
npx playwright install webkit        # once, on Ubuntu or Debian
PAPERUS_E2E_BROWSER=webkit npm test
npm run test:webkit                  # elsewhere: WebKit in Playwright's container (Docker)
```

`test:webkit` starts the browser in Playwright's image of the same version
and the tests here against it; arguments after `--` go to `playwright test`.
A test that needs one engine (pinching through Chromium's DevTools) checks
`browserName`.

`scripts/serve.sh`, started by Playwright, drops and creates `paperus_e2e`
(it refuses other names), migrates it, and starts the worker and the API on
port 8100 (`PAPERUS_E2E_PORT`) with files in a temporary folder; Playwright
stops them after the tests. Their logs are in `server-logs/`; failed tests
leave a trace and screenshot in `test-results/` (`npx playwright show-trace …`).
It never uses the dev database or the dev servers, and refuses to start if
something already listens on its port.

## Tests

- `setup.ts`: the first run, creating the administrator; the other tests use
  that login.
- `auth`: login needed, wrong password, log in and out.
- `papers`: upload a PDF (made in the test, `fixtures/pdf.ts`), the worker
  reads it, keyword search finds it; edit the title, add and remove tags.
- `organize`: collections, trash and restore, archive and take out, keywords
  from an import folded on the paper.
- `place`: Back from a paper returns to the same place in a long library,
  also when papers were added meanwhile.
- `authors`: from a paper to its author's page; a paper split off to
  another person of the same name; a shared name decided under Manage →
  Authors; merged again; the author page on a phone.
- `filter`: the library filtered by a tag clicked in the list, more rules
  in the Filter panel, saved as a smart collection, cleared; by an author
  (in the list and on a paper's page); the Filter button beside the count
  on a phone.
- `settings`: an access token: create, use from outside the browser, revoke.
- `dates`: the European date format: set by the administrator, typed into a
  smart collection's date field, shown in its description and a token's
  expiry; set back to the browser's at the end.
- `oauth`: an app registers, the consent page, the code traded for a token,
  disconnecting; an unknown app refused.
- `app-login`: the paperus app's login in the browser: confirmed on
  `/app-login`, the code on the app's loopback address traded for a session;
  cancelled; refused for an address not on this computer.
- `phone`: on a phone-sized screen (and a tablet held upright), pages have no
  sideways scroll; the menu
  drawer; a long chapter name keeps the PDF toolbar on one line and wraps in
  the contents.
- `sharing` (runs last: groups change what dialogs ask): two people, a group,
  a paper shared with it; who sees what.

Each test makes its own papers with words of its own, so tests run in
parallel on one server without stepping on each other.

`npm run screenshots` (`screenshots.config.ts`, `screenshots/`) takes the
homepage's pictures instead (`site/screenshots/`, see docs/operations.md),
and `npm run demo` records the homepage's demo (`demo/README.md`), both
against the same fresh server.
