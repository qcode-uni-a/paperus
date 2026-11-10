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
- Only the app's own page may call the app (`capabilities/start.json`); a
  library's website, a remote address, gets no access to it.

Log in inside the window, as on the website. Still to come: logging in
in the system's browser, "Open with", notifications, installers.

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
