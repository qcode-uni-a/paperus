# Apps

paperus as an app on computers and phones: connected to a server, or with
a library of its own on the computer, and later with papers kept offline
and synced. Planned; the steps (under Order) are issues (#30, #39, #40).

## One app, two kinds of library

One app, called paperus like the rest, lists libraries the way a mail
program lists accounts:

- **On a server**: its address, then a login. The app shows that server's
  paperus.
- **On this computer** (computers only): the app starts a paperus of its
  own in the background and shows that one. Downloaded on first use, so
  people who only connect to a server keep a small app.

Both kinds are a paperus server with its website; they differ only in where
the server runs. So one app rather than two: one interface, one release
pipeline, one signing, and a person can have their group's server and a
private library side by side. Phones get only the first kind (no Postgres
or Python there).

## A shell around the website

The interface is the website (`web/`), which every browser user needs
anyway. The app wraps it rather than repeating it: the PDF reader, fluent
mode (its page layouts come from the server), annotations, the library, search,
notes and settings exist once.

**Tauri 2** for all platforms: Windows, macOS, Linux, Android and iOS from
one project, about 10 MB. It uses the system's browser engine: WebView2
(Chromium) on Windows, the Android System WebView, WebKit on macOS and iOS,
WebKitGTK on Linux. So the e2e tests run in WebKit as well, before the app
(also for Safari on iPhones).

| | Computers | Phones | Size | Browser engine |
| --- | --- | --- | --- | --- |
| Tauri 2 | yes | yes, newer, fewer plugins | ~10 MB | the system's |
| Capacitor | no | yes, mature | small | the system's |
| Electron | yes | no | ~100 MB more | its own Chromium |

If Tauri's phone support proves too thin when Android comes, Capacitor
wraps the same website on phones; changing a shell costs little, since
both only wrap the website.

Not chosen: Flutter, React Native, Kotlin/Compose Multiplatform, .NET MAUI,
native Swift and Kotlin. Each would mean writing the interface a second
time and keeping two in step, the PDF reader and fluent mode above all
(they build on pdf.js's text layer). Flutter's own drawing engine would
look the same everywhere and feel more native on phones, but its web
version draws on a canvas, a poor fit for the website it would have to
replace.

## What the app adds

- **Login in the system browser**, not inside the app (some identity
  providers refuse logins in embedded browsers). The server's OAuth login
  with PKCE (`api/oauth.py`, made for MCP clients) does most of it: the app
  opens the browser (`/app-login`, where the person confirms), gets a code
  back on a loopback address (computers) or an app link (phones), and
  trades it once for a session (`/api/oauth/app-session`; the code has no
  scopes, so it gives no tokens). A session like a browser's: logging out
  in the app ends it (built: `app/src-tauri/src/login.rs`).
- **Adding from outside**: "Open with → paperus" for PDFs and other files;
  on phones "Share → paperus" from the browser, the extension's job there.
- **Notifications** from the bell as system notifications, and `paperus://`
  links to papers and notes.

At first the app loads the website from the server it is connected to, so
the website and the server's API always match. Offline (below) keeps that
rule.

## A library on this computer

A paperus for one person, downloaded by the app on first use:

- **Postgres with pgvector**: prebuilt binaries, the data in the app's
  folder (as on a server: the database, then `storage_path` for files).
- **Server and worker**: Python packaged to run without being installed;
  migrations run on start, as on a server.
- **ML service**, optional: ONNX, no torch; its models download on first
  use. Without it, keyword search only.

About 150 MB for the library, about 100 MB more for ML plus its models
(estimates). It listens on 127.0.0.1 only, on a random port, and only to
the app (a secret the app holds, the `Host` header checked), so no website
and no other program on the computer reads it. Moving it to a server later:
export and import ([export.md](export.md)).

## Offline and sync

The goal: papers kept on the device and read without a connection, changes
made offline sent when back online. For a server library, in the app on
every platform (and the installable website, as far as browsers allow).

- **What is kept**: papers marked "available offline" (or whole
  collections) and recently opened ones: their details, tags, collections,
  notes, annotations, reading positions, and their files.
- **The website offline**: the app keeps the copy of the server's website
  it last loaded, so offline it runs the same version as the server it
  synced with; never a website newer or older than the server's API.
- **An offline layer** between the pages and the API (all calls already go
  through the generated client, `web/src/lib/api/client.ts`): online,
  answers for kept papers are stored too; offline, reads come from the
  store and changes go into a queue. Kept in the app's own storage, not the
  browser's, which the system may clear.
- **Pulling** (done on the server): change numbers (`changes.py`) stamp
  items (with their versions, identifiers and files), tags, collections,
  notes, annotations and reading positions. What is deleted for good, or
  leaves a library (moved, annotations no longer shared), is recorded as a
  removal there. `GET /api/changes?since=N` gives all of it in one answer:
  the number for next time, the libraries the person reads now (what a
  device keeps from others is out of reach: a group left; a new one is
  synced from 0 with `library=`), the removals, then the records as they
  are now. A device applies the removals first, then the rest. Removals
  are kept a year: a device offline for longer gets 410, sends its own
  changes (they need no removals), tells the person it is getting the
  library again, and syncs from 0.
- **Pushing**: queued changes sent in order with `If-Match`, as now; on 412
  the conflict is shown, nothing overwritten. Changes as small operations
  that merge (add a tag, remove one from a collection, one annotation)
  rather than whole lists; new records with IDs made on the device
  (UUIDv7, as on the server), and a create sent twice after a dropped
  connection makes one record (done on the server for notes, tags,
  collections and annotations, `api/ids.py`; papers later).
- **Files** by SHA-256: only missing ones are downloaded.
- **Search offline**: keyword search in the kept papers; search by meaning
  needs the server (a small model on the device later perhaps).

Until then, new API and website code keeps this possible: writes as small
operations, every synced kind with change numbers, client-made IDs
accepted.

Two-way sync between a library on a computer and a server's library (two
servers) is a later, larger question; the same pulling and pushing would be
its base.

## Order

Each step usable on its own:

1. **WebKit in the e2e tests** (Safari's engine; also phones' Safari):
   done, every test in both engines in CI (`e2e/README.md`).
2. **The app on computers, connected to a server**: login in the system
   browser, "Open with", notifications; installers on each GitHub release.
   Begun (`app/`): the libraries listed and added, a library's website in
   the app's window, other sites' links in the system's browser,
   downloads; the OIDC login in the system's browser (passwords inside the
   window, as on the website); "Open with" for PDFs (Linux, macOS);
   notifications; installers (`.github/workflows/app.yml`).
3. **A library on this computer**, in the same app (#39). Begun: its parts
   built per platform in CI (`app/local/`, `.github/workflows/local.yml`:
   Linux, macOS on Apple silicon, Windows), made and started by the app
   (`app/src-tauri/src/local.rs`, see `app/README.md`), tested end to end
   on Linux. Not yet: search by meaning there (the ML service), attaching
   the parts to releases, Intel Macs.
4. **Android** (#30): "Share → paperus".
5. **Offline**: what the server needs for sync (above), then the offline
   layer, kept papers, the queue.
6. **iOS**, with an Apple developer account (#40).

## Open

- Signing: Apple ($99 a year, or the fee waiver, #40), Windows (a code
  signing certificate), Linux (none needed; AppImage, Flatpak?).
- Updates of the app and of the library on the computer: Tauri's updater,
  or the stores'.
- Pen input on tablets: enough in the website (pointer events), or native?
