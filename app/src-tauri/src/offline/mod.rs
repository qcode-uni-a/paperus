//! Offline use of a server library (docs/apps.md, "Offline and sync"):
//! while it is open and reachable, a copy of what the person sees there is
//! kept up to date every minute with the window's login (`store`): the
//! details of every paper, notes, tags, collections, annotations and where
//! one stopped reading, from `/api/changes`; the account and lists the
//! website asks for first; the papers opened last whole, with their PDFs;
//! and the website itself as last loaded (`site`). When the library cannot
//! be reached, the window opens that copy at an address of the app's own,
//! where the copy answers the website's calls (`answer`).

mod answer;
mod site;
mod store;
mod write;

use std::{
    collections::HashSet,
    fs,
    path::PathBuf,
    sync::{Mutex, mpsc},
    thread,
    time::{Duration, Instant},
};

use serde::Deserialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use tauri::{
    AppHandle, Manager, UriSchemeContext, UriSchemeResponder, Url, WebviewWindow,
    http::{Request, Response},
};

use crate::{MAIN, libraries};
pub use store::Store;

/// The level of the server's `sync` feature (`/api/version`) this app
/// understands; another (or none: before 0.0.22) means no offline use.
pub const SYNC: i64 = 1;

/// The scheme of the address offline copies are opened at.
pub const SCHEME: &str = "paperus-offline";

const EVERY: Duration = Duration::from_secs(60);
/// The papers opened last are kept whole, with their files.
const KEPT_RECENT: usize = 20;
/// Answers the website asks for first, kept as they come.
const ACCOUNT: [&str; 7] = [
    "/api/auth/me",
    "/api/auth/methods",
    "/api/libraries",
    "/api/groups",
    "/api/tags",
    "/api/collections",
    "/api/me/notifications",
];

/// The library whose copy is open (its address), if any.
static OPEN: Mutex<Option<String>> = Mutex::new(None);
/// Wakes the sync before its minute is up.
static WAKE: Mutex<Option<mpsc::Sender<()>>> = Mutex::new(None);

/// Where an offline copy is opened: the scheme's address on this system.
pub fn address() -> Url {
    let base = if cfg!(any(windows, target_os = "android")) {
        format!("http://{SCHEME}.localhost/")
    } else {
        format!("{SCHEME}://localhost/")
    };
    Url::parse(&base).expect("a valid address")
}

/// The folder of a library's copy: a name from its address.
fn folder(app: &AppHandle, library: &str) -> Option<PathBuf> {
    let name = hex(&Sha256::digest(library.as_bytes())[..12]);
    let folder = app.path().app_data_dir().ok()?.join("offline").join(name);
    fs::create_dir_all(&folder).ok()?;
    Some(folder)
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn open_store(app: &AppHandle, library: &str) -> Option<Store> {
    Store::open(&folder(app, library)?.join("library.sqlite")).ok()
}

#[derive(Deserialize)]
struct ServerVersion {
    #[serde(default)]
    features: std::collections::HashMap<String, i64>,
}

/// Whether the library offers syncing as this app knows it; None if it
/// did not answer (asked again next time).
fn syncs(url: &str) -> Option<bool> {
    let mut response = libraries::agent()
        .get(format!("{url}/api/version"))
        .call()
        .ok()?;
    if !response.status().is_success() {
        // Before 0.0.22: no /api/version, so no syncing.
        return (response.status().as_u16() == 404).then_some(false);
    }
    let version: ServerVersion = response.body_mut().read_json().ok()?;
    Some(version.features.get("sync") == Some(&SYNC))
}

/// Whether the library answers (quickly).
pub fn reachable(url: &str) -> bool {
    ureq::Agent::config_builder()
        .timeout_global(Some(Duration::from_secs(4)))
        .http_status_as_error(false)
        .build()
        .new_agent()
        .get(format!("{url}/api/health"))
        .call()
        .is_ok_and(|response| response.status().is_success())
}

/// A change made offline that the library refused, for the app's page.
#[derive(serde::Serialize)]
pub struct Unsaved {
    library: String,
    name: String,
    seq: i64,
    what: String,
    why: String,
    /// What was written (a note's text, an annotation's comment).
    written: Option<String>,
}

/// The changes made offline that libraries refused.
pub fn unsaved(app: &AppHandle) -> Vec<Unsaved> {
    libraries::load(app)
        .libraries
        .into_iter()
        .filter(|library| !library.local)
        .flat_map(|library| {
            let set_aside = open_store(app, &library.url)
                .map(|store| store.unsaved())
                .unwrap_or_default();
            set_aside.into_iter().map(move |(seq, what, why, body)| {
                let written = body
                    .and_then(|body| serde_json::from_str::<Value>(&body).ok())
                    .and_then(|body| {
                        ["text", "comment"]
                            .into_iter()
                            .find_map(|field| body[field].as_str().map(str::to_owned))
                    })
                    .filter(|written| !written.is_empty());
                Unsaved {
                    library: library.url.clone(),
                    name: library.name.clone(),
                    seq,
                    what,
                    why,
                    written,
                }
            })
        })
        .collect()
}

/// The person has seen a change set aside.
pub fn dismiss(app: &AppHandle, library: &str, seq: i64) -> Result<(), String> {
    open_store(app, library)
        .ok_or("No copy of that library.")?
        .dismiss(seq)
        .map_err(|error| error.to_string())
}

/// Whether there is a copy of the library to open: synced, with its
/// website, and a login kept (logged out, it is not opened: nobody could log
/// in offline).
pub fn has_copy(app: &AppHandle, library: &str) -> bool {
    let Some(folder) = folder(app, library) else {
        return false;
    };
    let logged_in = Url::parse(library).is_ok_and(|url| libraries::kept_login(app, &url).is_some());
    logged_in
        && site::has_copy(&folder)
        && open_store(app, library).is_some_and(|store| store.since() > 0 && !store.logging_out())
}

/// Delete the copy of a library from this device (logged out): what was
/// synced, the papers kept, the website. Changes not sent yet stay, sent
/// after the next login (or before the login ends, logging out offline).
fn forget_copy(app: &AppHandle, library: &str) {
    if let Some(mut store) = open_store(app, library) {
        let _ = store.clear();
    }
    if let Some(folder) = folder(app, library) {
        for part in ["files", "site", "site.next", "site.old"] {
            let _ = fs::remove_dir_all(folder.join(part));
        }
    }
}

/// The library's login ended (logged out, or too old): forgotten, and the
/// copy with it.
fn logged_out(app: &AppHandle, library: &str) {
    if let Ok(url) = Url::parse(library) {
        libraries::remember_session(app, &url, None);
    }
    forget_copy(app, library);
}

/// Logged out in the copy, offline: the copy goes at once, and the window
/// to the app's page; what was changed offline is sent when the library is
/// back, then the login ends there too (`finish_logouts`).
fn log_out_offline(app: &AppHandle, library: &str) {
    forget_copy(app, library);
    if let Some(store) = open_store(app, library) {
        let _ = store.enqueue(&store::Queued {
            method: "POST".into(),
            path: "/api/auth/logout".into(),
            what: "Logging out".into(),
            ..store::Queued::default()
        });
        let _ = store.set_logging_out(true);
    }
    if let Ok(mut open) = OPEN.lock() {
        *open = None;
    }
    if let Some(main) = app.get_webview_window(MAIN) {
        let _ = main.navigate(crate::start_page());
    }
}

/// Logged out offline, for the app's page: the library, and how many
/// changes wait to be sent before the login ends there.
#[derive(serde::Serialize)]
pub struct LoggingOut {
    name: String,
    waiting: usize,
}

pub fn logging_out(app: &AppHandle) -> Vec<LoggingOut> {
    libraries::load(app)
        .libraries
        .into_iter()
        .filter(|library| !library.local)
        .filter_map(|library| {
            let store = open_store(app, &library.url)?;
            store.logging_out().then(|| LoggingOut {
                name: library.name,
                // Not counting the logout itself.
                waiting: store.queued().len().saturating_sub(1),
            })
        })
        .collect()
}

/// Libraries logged out offline, back within reach: their queue sent, the
/// logout last, then the login forgotten.
fn finish_logouts(app: &AppHandle) {
    for library in libraries::load(app).libraries {
        let Some(store) = open_store(app, &library.url) else {
            continue;
        };
        if library.local || !store.logging_out() || !reachable(&library.url) {
            continue;
        }
        let Ok(url) = Url::parse(&library.url) else {
            continue;
        };
        let Some(token) = libraries::kept_login(app, &url) else {
            let _ = store.set_logging_out(false);
            continue;
        };
        let server = Server {
            url: &library.url,
            token: &token,
            logged_out: Default::default(),
        };
        if push(&server, &store) || server.logged_out.get() {
            libraries::remember_session(app, &url, None);
            let _ = store.set_logging_out(false);
        }
    }
}

/// The library whose copy is open.
pub fn open_library() -> Option<String> {
    OPEN.lock().ok().and_then(|open| open.clone())
}

/// Open the copy of ``library`` in ``window``.
pub fn open(window: &WebviewWindow, library: &str) -> tauri::Result<()> {
    if let Ok(mut open) = OPEN.lock() {
        *open = Some(library.to_owned());
    }
    window.navigate(address())
}

/// Answers the offline copy's address: the website's files, and its calls
/// from the copy.
pub fn serve(
    context: UriSchemeContext<'_, tauri::Wry>,
    request: Request<Vec<u8>>,
    responder: UriSchemeResponder,
) {
    let app = context.app_handle().clone();
    thread::spawn(move || {
        let library = OPEN.lock().ok().and_then(|open| open.clone());
        let response = match library.and_then(|library| Some((folder(&app, &library)?, library))) {
            Some((folder, library)) => {
                let path = request.uri().path();
                if request.method() == "POST" && path == "/api/auth/logout" {
                    log_out_offline(&app, &library);
                    Response::builder()
                        .status(204)
                        .body(Vec::new())
                        .expect("a response")
                } else if path.starts_with("/api/") {
                    match open_store(&app, &library) {
                        Some(store) => answer::answer(&store, &folder, &request),
                        None => answer::unavailable(),
                    }
                } else {
                    site::file(&folder, path)
                }
            }
            None => Response::builder()
                .status(404)
                .body(Vec::new())
                .expect("a response"),
        };
        responder.respond(response);
    });
}

/// Sync now (a library's page loaded: just logged in, say).
pub fn nudge() {
    if let Ok(sender) = WAKE.lock()
        && let Some(sender) = sender.as_ref()
    {
        let _ = sender.send(());
    }
}

/// Keeps the copy of the library open in the main window up to date,
/// every minute while it is reachable.
pub fn start(app: AppHandle) {
    let (wake, woken) = mpsc::channel();
    if let Ok(mut sender) = WAKE.lock() {
        *sender = Some(wake);
    }
    thread::spawn(move || {
        // Libraries that do not sync as this app knows it, asked again
        // after a while (the server may be updated).
        let mut checked: std::collections::HashMap<String, (bool, Instant)> = Default::default();
        loop {
            finish_logouts(&app);
            let _ = sync(&app, &mut checked);
            let _ = woken.recv_timeout(EVERY);
            while woken.try_recv().is_ok() {}
        }
    });
}

fn sync(
    app: &AppHandle,
    checked: &mut std::collections::HashMap<String, (bool, Instant)>,
) -> Option<()> {
    let window = app.get_webview_window(MAIN)?;
    let library = libraries::of(app, &window.url().ok()?)?;
    if library.local {
        return None;
    }
    let url = library.url.clone();
    let known = checked
        .get(&url)
        .filter(|(_, at)| at.elapsed() < Duration::from_secs(3600));
    let syncs = match known {
        Some((syncs, _)) => *syncs,
        None => {
            let found = syncs(&url)?;
            checked.insert(url.clone(), (found, Instant::now()));
            found
        }
    };
    if !syncs {
        return None;
    }
    let Some(token) = libraries::session(&window, &Url::parse(&url).ok()?) else {
        eprintln!("offline: {url}: not logged in, not synced");
        return None;
    };
    let folder = folder(app, &url)?;
    let mut store = Store::open(&folder.join("library.sqlite")).ok()?;
    let server = Server {
        url: &url,
        token: &token,
        logged_out: Default::default(),
    };
    // What was changed offline first: what comes back then includes it.
    if !push(&server, &store) {
        if server.logged_out.get() {
            logged_out(app, &url);
        }
        return None;
    }
    let set_aside = store.unsaved().len();
    if set_aside > 0 && set_aside != told(&url) {
        tell(app, &library.name, set_aside);
        remember_told(&url, set_aside);
    }
    let before = store.since();
    if let Err(error) = store::pull(&mut store, &url, &token) {
        eprintln!("offline: {url}: not synced: {error}");
        // The login ended (logged out, or too old): not used again, and
        // the copy goes with it.
        if error.ends_with(": 401") {
            logged_out(app, &url);
        }
        return None;
    }
    if store.since() != before || store.answer(ACCOUNT[0]).is_none() {
        for path in ACCOUNT {
            let _ = server.keep(&store, path, store.since());
        }
    }
    keep_papers(&server, &store, &folder);
    site::copy(&url, &folder).ok()
}

/// How many changes set aside the person was told of, per library.
static TOLD: Mutex<Vec<(String, usize)>> = Mutex::new(Vec::new());

fn told(url: &str) -> usize {
    TOLD.lock()
        .ok()
        .and_then(|told| told.iter().find(|(at, _)| at == url).map(|(_, n)| *n))
        .unwrap_or(0)
}

fn remember_told(url: &str, count: usize) {
    if let Ok(mut told) = TOLD.lock() {
        told.retain(|(at, _)| at != url);
        told.push((url.to_owned(), count));
    }
}

/// The person is told of changes made offline the library refused.
fn tell(app: &AppHandle, library: &str, count: usize) {
    use tauri_plugin_notification::NotificationExt;
    let changes = if count == 1 { "1 change" } else { "changes" };
    let _ = app
        .notification()
        .builder()
        .title(library)
        .body(format!(
            "{} made offline could not be saved: see Library → Libraries…",
            if count == 1 {
                changes.to_owned()
            } else {
                format!("{count} {changes}")
            }
        ))
        .show();
}

/// Send the changes made offline, in order. One the library refuses
/// (changed or gone meanwhile) is set aside for the person to see; the
/// first that cannot be sent (offline again, logged out) stops it.
/// Whether all were sent.
fn push(server: &Server, store: &Store) -> bool {
    for change in store.queued() {
        let (status, detail) = match server.send(&change) {
            Ok(answer) => answer,
            Err(error) => {
                eprintln!(
                    "offline: {} {}: not sent: {error}",
                    change.method, change.path
                );
                return false;
            }
        };
        if !(200..300).contains(&status) {
            eprintln!(
                "offline: {} {}: {status} {detail}",
                change.method, change.path
            );
        }
        let why = match status {
            200..=299 => {
                let _ = store.dequeue(change.seq);
                continue;
            }
            412 => "It was changed on the server meanwhile.".to_owned(),
            404 => "It is no longer in the library.".to_owned(),
            403 => "You may no longer change it.".to_owned(),
            409 | 422 => format!("The library refused it: {detail}"),
            401 => {
                server.logged_out.set(true);
                return false;
            }
            _ => return false,
        };
        let _ = store.set_aside(&change, &why);
    }
    true
}

/// The library, asked with the window's login.
struct Server<'a> {
    url: &'a str,
    token: &'a str,
    /// The library answered 401: its login ended.
    logged_out: std::cell::Cell<bool>,
}

impl Server<'_> {
    fn get(&self, path: &str) -> Result<(String, Vec<u8>), String> {
        let mut response = libraries::agent_for_downloads()
            .get(format!("{}{path}", self.url))
            .header(
                "Cookie",
                &format!("{}={}", libraries::SESSION_COOKIE, self.token),
            )
            .call()
            .map_err(|error| error.to_string())?;
        if !response.status().is_success() {
            return Err(format!("{path}: {}", response.status()));
        }
        let media_type = response
            .headers()
            .get("content-type")
            .and_then(|value| value.to_str().ok())
            .unwrap_or("application/json")
            .to_owned();
        let body = response
            .body_mut()
            .with_config()
            .limit(1 << 31)
            .read_to_vec()
            .map_err(|error| error.to_string())?;
        Ok((media_type, body))
    }

    /// Send a change made offline: its status, and the server's reason.
    fn send(&self, change: &store::Queued) -> Result<(u16, String), String> {
        let url = format!("{}{}", self.url, change.path);
        let cookie = format!("{}={}", libraries::SESSION_COOKIE, self.token);
        let agent = libraries::agent();
        let response = if change.method == "DELETE" {
            let mut request = agent.delete(&url).header("Cookie", &cookie);
            if let Some(version) = &change.if_match {
                request = request.header("If-Match", version);
            }
            request.call()
        } else {
            let mut request = match change.method.as_str() {
                "PUT" => agent.put(&url),
                "PATCH" => agent.patch(&url),
                _ => agent.post(&url),
            }
            .header("Cookie", &cookie)
            .header("Content-Type", "application/json");
            if let Some(version) = &change.if_match {
                request = request.header("If-Match", version);
            }
            match &change.body {
                Some(body) => request.send(body.as_bytes()),
                None => request.send_empty(),
            }
        };
        let mut response = response.map_err(|error| error.to_string())?;
        let status = response.status().as_u16();
        let detail = response
            .body_mut()
            .read_json::<Value>()
            .ok()
            .and_then(|body| body["detail"].as_str().map(str::to_owned))
            .unwrap_or_default();
        Ok((status, detail))
    }

    /// Keep the answer to ``path`` (as of change ``change``).
    fn keep(&self, store: &Store, path: &str, change: i64) -> Result<(), String> {
        let (media_type, body) = self.get(path)?;
        store
            .keep_answer(path, change, &media_type, &body)
            .map_err(|error| error.to_string())
    }
}

/// The papers in a collection and those inside it (from the copy).
fn papers_in(store: &Store, collection: &str) -> Vec<String> {
    let collections = store.all("collection");
    let mut inside = HashSet::from([collection.to_owned()]);
    loop {
        let more: Vec<String> = collections
            .iter()
            .filter(|c| {
                c["parent_id"]
                    .as_str()
                    .is_some_and(|parent| inside.contains(parent))
                    && c["id"].as_str().is_some_and(|id| !inside.contains(id))
            })
            .filter_map(|c| c["id"].as_str().map(str::to_owned))
            .collect();
        if more.is_empty() {
            break;
        }
        inside.extend(more);
    }
    store
        .all("item")
        .into_iter()
        .filter(|item| {
            item["deleted_at"].is_null()
                && item["collection_ids"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .any(|id| id.as_str().is_some_and(|id| inside.contains(id)))
        })
        .filter_map(|item| item["id"].as_str().map(str::to_owned))
        .collect()
}

/// A smart collection's papers, as the server finds them (its rules).
fn smart_papers(server: &Server, collection: &str) -> Vec<String> {
    let mut found = Vec::new();
    let mut before: Option<String> = None;
    loop {
        let after = before
            .as_ref()
            .map(|id| format!("&before={id}"))
            .unwrap_or_default();
        let Ok((_, body)) = server.get(&format!(
            "/api/items?collection={collection}&limit=200{after}"
        )) else {
            break;
        };
        let page: Vec<Value> = serde_json::from_slice(&body).unwrap_or_default();
        let ids: Vec<String> = page
            .iter()
            .filter_map(|item| item["id"].as_str().map(str::to_owned))
            .collect();
        let done = ids.len() < 200;
        before = ids.last().cloned();
        found.extend(ids);
        if done {
            break;
        }
    }
    found
}

/// The papers kept whole: those opened last, those marked "Keep offline",
/// and those in collections marked so (new ones too: asked anew each sync).
fn kept(store: &Store, server: &Server) -> Vec<String> {
    let mut views = store.all("view");
    views.sort_by(|a, b| {
        let at = |view: &Value| view["viewed_at"].as_str().unwrap_or_default().to_owned();
        at(b).cmp(&at(a))
    });
    let recent = views
        .iter()
        .filter_map(|view| view["item_id"].as_str().map(str::to_owned))
        .filter(|id| store.get("item", id).is_some())
        .take(KEPT_RECENT);
    let marked = store.marked();
    let in_collections = marked.collections.iter().flat_map(|collection| {
        let smart = store
            .get("collection", collection)
            .is_some_and(|found| !found["rules"].is_null());
        if smart {
            smart_papers(server, collection)
        } else {
            papers_in(store, collection)
        }
    });
    let mut kept: Vec<String> = Vec::new();
    for id in recent
        .chain(marked.items.iter().cloned())
        .chain(in_collections)
    {
        if !kept.contains(&id) && store.get("item", &id).is_some() {
            kept.push(id);
        }
    }
    kept
}

/// Mark (or unmark) a paper or collection of the library open in
/// ``window`` "Keep offline", and tell the page.
pub fn mark(window: &WebviewWindow, kind: &str, id: &str, on: bool) {
    let app = window.app_handle();
    let Some(library) = window.url().ok().and_then(|url| libraries::of(app, &url)) else {
        return;
    };
    if let Some(store) = open_store(app, &library.url) {
        let _ = store.mark(kind, id, on);
    }
    tell_kept(window);
    nudge();
}

/// Tell the page what this device keeps offline
/// (`window.paperusApp.kept`, web/src/lib/offline.svelte.ts).
pub fn tell_kept(window: &WebviewWindow) {
    let app = window.app_handle();
    // A library's page, or its copy offline.
    let Ok(url) = window.url() else {
        return;
    };
    let copy =
        url.scheme() == SCHEME || url.host_str() == Some(format!("{SCHEME}.localhost").as_str());
    let Some(library) = libraries::of(app, &url)
        .map(|library| library.url)
        .or_else(|| copy.then(open_library).flatten())
    else {
        return;
    };
    let Some(store) = open_store(app, &library) else {
        return;
    };
    let marked = store.marked();
    let _ = window.eval(format!(
        "if (window.paperusApp) {{ window.paperusApp.kept = {}; \
         window.dispatchEvent(new Event('paperus-kept')); }}",
        serde_json::json!({
            "items": marked.items,
            "collections": marked.collections,
            "available": store.available(),
        })
    ));
}

/// Keep the papers to read offline whole: their page, their files with
/// their layouts (fluent mode) and annotations' page marks, references and
/// cited-by; again when they changed. Others let go.
fn keep_papers(server: &Server, store: &Store, folder: &std::path::Path) {
    let files = folder.join("files");
    let _ = fs::create_dir_all(&files);
    let kept = kept(store, server);
    let mut wanted: HashSet<String> = HashSet::new();
    let mut available: Vec<String> = Vec::new();
    for id in &kept {
        let Some(item) = store.get("item", id) else {
            continue;
        };
        let change = item["change"].as_i64().unwrap_or(0);
        let page = format!("/api/items/{id}");
        let current = store
            .answer(&page)
            .is_some_and(|(kept_at, _, _)| kept_at >= change);
        let mut paths = vec![
            page.clone(),
            format!("/api/items/{id}/references"),
            format!("/api/items/{id}/cited-by"),
        ];
        for file in item["files"].as_array().into_iter().flatten() {
            let Some(file_id) = file["id"].as_str() else {
                continue;
            };
            wanted.insert(file_id.to_owned());
            paths.push(format!("/api/files/{file_id}/layout"));
            paths.push(format!("/api/files/{file_id}/annotations"));
            let path = files.join(file_id);
            if !path.exists()
                && let Ok((_, body)) = server.get(&format!("/api/files/{file_id}/content"))
            {
                let partial = files.join(format!("{file_id}.partial"));
                if fs::write(&partial, body).is_ok() {
                    let _ = fs::rename(&partial, &path);
                }
            }
        }
        if !current {
            for path in &paths {
                let _ = server.keep(store, path, change);
            }
        }
        let files_kept = item["files"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|file| file["id"].as_str())
            .all(|file| files.join(file).exists());
        if files_kept && store.answer(&page).is_some() {
            available.push(id.clone());
        }
    }
    let _ = store.set_available(&available);
    // Let go of what is no longer kept.
    let keep: HashSet<&String> = kept.iter().collect();
    for prefix in ["/api/items/", "/api/files/"] {
        for path in store.answer_paths(prefix) {
            let id = path.split('/').nth(3).unwrap_or_default().to_owned();
            let gone = if prefix == "/api/items/" {
                !keep.contains(&id)
            } else {
                !wanted.contains(&id)
            };
            if gone {
                let _ = store.drop_answer(&path);
            }
        }
    }
    if let Ok(entries) = fs::read_dir(&files) {
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().into_owned();
            if !wanted.contains(&name) {
                let _ = fs::remove_file(entry.path());
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn named_after_the_address() {
        assert_eq!(hex(&[0, 15, 255]), "000fff");
    }
}
