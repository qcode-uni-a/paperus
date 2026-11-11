# The app

paperus for computers: a paperus server's website in a window of its own
([apps.md](../docs/apps.md)). Tauri 2; the window is the system's browser
engine (WebKitGTK on Linux, WebKit on macOS, WebView2 on Windows).

- `start/`: the app's own page, listing the libraries (servers) and
  connecting to another. Plain HTML and JavaScript, no build.
- `src-tauri/`: the app. `libraries.rs` keeps the libraries (in the app's
  config folder, `libraries.json`) and checks that an address is a paperus
  (its public `/api/auth/methods`); `lib.rs` makes the windows; `local.rs`
  runs the library on this computer (below).
- `local/`: the library on this computer's parts: `build.sh` builds them
  for a platform, `smoke.sh` starts them once.

What the app does around the website:

- Opens the library opened last; Library → Libraries… (Ctrl+Shift+L) goes
  back to the list.
- Links to other sites open in the system's browser; the library's own
  links that ask for a new tab open in another window of the app (the
  login carries over).
- Downloads go into the Downloads folder.
- "Open with → paperus" for PDFs (`open_with.rs`; Linux and macOS for now):
  each file is added to the library shown, with the window's login, as the
  website's upload does, and its paper shown. Opening the app again (or a
  file with it) goes to the one already open. paperus is only offered for
  PDFs, never made the program that opens them (on macOS an "alternate"
  one; Windows' installer would make it the default, so not there yet).
- Files dropped on the window go to the website (its drop zone).
- The bell's notifications as the system's (`notices.rs`): asked for every
  minute with the window's login; those that come while the app runs, and
  not while its window is in front.
- Offline use of server libraries (`offline/`, [apps.md](../docs/apps.md),
  "Offline and sync"): while one is open, a copy in SQLite in the app's
  data folder, synced every minute and when a page loads (`/api/changes`,
  with the window's login), whole with their PDFs the papers opened last
  and those marked "Keep offline" (alone or by collection: the website asks
  with `paperus-app:keep`, the app tells it `window.paperusApp.kept`), and
  the website itself (`site.rs`). Out of reach, the window opens the
  copy at `paperus-offline://`, where the app answers the website's calls
  (`answer.rs`) and queues its changes (`write.rs`), sent when the library
  is back; those it refuses are listed on the app's page. Only with
  servers that offer it (`/api/version`).
- Only the app's own page may call the app (`capabilities/start.json`); a
  library's website, a remote address, gets no access to it.

Logging in: with a password inside the window, as on the website; with
the OIDC login in the system's browser (`login.rs`), where identity
providers allow it (some refuse a window inside an app) and one may be
logged in already. The website knows it is in the app
(`window.paperusApp`, set by the app) and its OIDC button then asks the app
(`paperus-app:login`): the app registers as an OAuth client of the library,
opens `/app-login` in the browser, where the person confirms, gets a
one-time code back on a loopback address (`http://127.0.0.1:<port>/done`),
and trades it with its PKCE verifier for a session
(`/api/oauth/app-session`), which it sets as the website's own login
cookie. A session like a browser's, not a connected app: logging out in the
app ends it.

## A library on this computer

For one person, without a server (`local.rs`, [apps.md](../docs/apps.md)):
"Make a library on this computer" on the app's page. Its parts come as one
file per platform from the release, `paperus-local-<version>-<target>.tar.gz`
(built by `local/build.sh` in `.github/workflows/local.yml`: a standalone
Python with the server and its locked dependencies, PostgreSQL with
pgvector built against it, the website), downloaded once per version and
checked against its SHA-256 (`.sha256` beside it). The first start makes a
database (`initdb`, a random password) and the library's only person (`me`,
a random password); both are kept in `secrets.json` with the data, in the
app's data folder (`library/`: the database, files, backups, logs). Each
start runs PostgreSQL, `paperus serve` and `paperus worker`, all on
127.0.0.1 only, migrates the schema, logs the window in and opens it; the
app stops them when it ends, and the server and worker end with it however
it ends (`--stop-with-stdin`: their input is a pipe from the app). A
PostgreSQL left running by a crash is used again. No ML service yet: search
finds words.

`PAPERUS_LOCAL_BUNDLE`: a bundle's folder or .tar.gz to use instead of the
release's (development, tests).

Still to come: "Open with" on Windows; a click on a notification
opening its paper; search by meaning in the library on this computer (the
ML service in the bundle, its model downloaded on first use); Intel Macs'
bundle.

## Installers

`.github/workflows/app.yml` builds them for Linux (deb, rpm, AppImage),
Windows (setup .exe, msi) and macOS (one dmg for both kinds of Mac), by
hand (Actions → App installers) or for a release
([operations.md](../docs/operations.md), Releases). Not signed yet.

## Development

Needs Rust and, on Linux, WebKitGTK 4.1 (Ubuntu:
`libwebkit2gtk-4.1-dev librsvg2-dev libayatana-appindicator3-dev`; Arch:
`webkit2gtk-4.1`).

```sh
cd app
npm install
npm run dev          # the app, from source (connect it to http://localhost:5173)
npm run build        # installers for this system, in src-tauri/target/release/bundle
npm run icons        # the icons again, from web/static/favicon.svg

cd src-tauri
cargo fmt && cargo clippy --all-targets && cargo test
```

## Tests

Unit tests in the Rust files (`cargo test`). `tests/run.sh` runs the
app's journeys (`tests/journeys.mjs`): the app itself, driven through
tauri-driver (WebDriver; `cargo install tauri-driver`, and WebKitWebDriver:
Ubuntu `webkitgtk-webdriver`, Arch's comes with `webkit2gtk-4.1`), against
the e2e tests' paperus (as `e2e/scripts/serve.sh` starts it; needs
`web/build` and the compose Postgres). Connecting to a library, the
website kept out of the app, logging in in the browser (whose part goes
over HTTP; its page is in `e2e/tests/app-login.spec.ts`), "Open with",
and offline (the network to the library cut by a stand-in proxy): the app
started again opens its copy, with the paper opened last and its PDF; an
annotation made offline reaches the server when it is back. On
its own display (Xvfb, else GTK's Broadway) and session bus; the
browser it opens is a stand-in that writes the address down. CI runs it.

`tests/local.sh <bundle>` (`tests/local.mjs`): the library on this
computer with a built bundle: made from the app's page, logged in, opened
again by itself after the app was killed (its PostgreSQL used again), no
server or worker left afterwards. `.github/workflows/local.yml` runs it
after building the Linux bundle, whose `local/smoke.sh` has started it
once already.
