# The app

paperus for computers: a paperus server's website in a window of its own
([apps.md](../docs/apps.md)). Tauri 2; the window is the system's browser
engine (WebKitGTK on Linux, WebKit on macOS, WebView2 on Windows).

- `start/`: the app's own page, listing the libraries (servers) and
  connecting to another. Plain HTML and JavaScript, no build.
- `src-tauri/`: the app. `libraries.rs` keeps the libraries (in the app's
  config folder, `libraries.json`) and checks that an address is a paperus
  (its public `/api/auth/methods`); `lib.rs` makes the windows.

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

Still to come: "Open with" on Windows, notifications.

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
