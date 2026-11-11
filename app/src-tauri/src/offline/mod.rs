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

/// Whether the library offers syncing as this app knows it.
fn syncs(url: &str) -> bool {
    libraries::agent()
        .get(format!("{url}/api/version"))
        .call()
        .ok()
        .filter(|response| response.status().is_success())
        .and_then(|mut response| response.body_mut().read_json::<ServerVersion>().ok())
        .is_some_and(|version| version.features.get("sync") == Some(&SYNC))
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

/// Whether there is a copy of the library to open: synced, with its website.
pub fn has_copy(app: &AppHandle, library: &str) -> bool {
    let Some(folder) = folder(app, library) else {
        return false;
    };
    site::has_copy(&folder) && open_store(app, library).is_some_and(|store| store.since() > 0)
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
                if path.starts_with("/api/") {
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
            let found = syncs(&url);
            checked.insert(url.clone(), (found, Instant::now()));
            found
        }
    };
    if !syncs {
        return None;
    }
    let token = libraries::session(&window, &Url::parse(&url).ok()?)?;
    let folder = folder(app, &url)?;
    let mut store = Store::open(&folder.join("library.sqlite")).ok()?;
    let before = store.since();
    store::pull(&mut store, &url, &token).ok()?;
    let server = Server {
        url: &url,
        token: &token,
    };
    if store.since() != before || store.answer(ACCOUNT[0]).is_none() {
        for path in ACCOUNT {
            let _ = server.keep(&store, path, store.since());
        }
    }
    keep_papers(&server, &store, &folder);
    site::copy(&url, &folder).ok()
}

/// The library, asked with the window's login.
struct Server<'a> {
    url: &'a str,
    token: &'a str,
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

    /// Keep the answer to ``path`` (as of change ``change``).
    fn keep(&self, store: &Store, path: &str, change: i64) -> Result<(), String> {
        let (media_type, body) = self.get(path)?;
        store
            .keep_answer(path, change, &media_type, &body)
            .map_err(|error| error.to_string())
    }
}

/// The papers kept whole: the ones opened last.
fn kept(store: &Store) -> Vec<String> {
    let mut views = store.all("view");
    views.sort_by(|a, b| {
        let at = |view: &Value| view["viewed_at"].as_str().unwrap_or_default().to_owned();
        at(b).cmp(&at(a))
    });
    views
        .iter()
        .filter_map(|view| view["item_id"].as_str().map(str::to_owned))
        .filter(|id| store.get("item", id).is_some())
        .take(KEPT_RECENT)
        .collect()
}

/// Keep the papers to read offline whole: their page, their files with
/// their layouts (fluent mode) and annotations' page marks, references and
/// cited-by; again when they changed. Others let go.
fn keep_papers(server: &Server, store: &Store, folder: &std::path::Path) {
    let files = folder.join("files");
    let _ = fs::create_dir_all(&files);
    let kept = kept(store);
    let mut wanted: HashSet<String> = HashSet::new();
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
    }
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
