# End-to-end tests

A real browser (Playwright, Chromium) against a real paperus: the API
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
- `phone`: on a phone-sized screen (and a tablet held upright), pages have no
  sideways scroll; the menu
  drawer; a long chapter name keeps the PDF toolbar on one line and wraps in
  the contents.
- `sharing` (runs last: groups change what dialogs ask): two people, a group,
  a paper shared with it; who sees what.

Each test makes its own papers with words of its own, so tests run in
parallel on one server without stepping on each other.
