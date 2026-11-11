//! The libraries the app knows (paperus servers), kept in the app's config
//! folder, and the check that an address is one.

use std::{
    collections::HashMap,
    fs,
    path::PathBuf,
    sync::{
        Mutex,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager, WebviewWindow};
use url::Url;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
pub struct Library {
    /// Where its website is: scheme, host and a path it may be served
    /// below, without a trailing slash.
    pub url: String,
    /// What the app calls it: its host, until servers name themselves.
    pub name: String,
    /// The library on this computer (`local.rs`): started by the app, its
    /// address changes when its port does.
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub local: bool,
}

#[derive(Debug, Default, Deserialize, Serialize)]
pub struct Saved {
    pub libraries: Vec<Library>,
    /// The library opened last: opened again when the app starts.
    pub last: Option<String>,
}

fn file(app: &AppHandle) -> Option<PathBuf> {
    Some(app.path().app_config_dir().ok()?.join("libraries.json"))
}

pub fn load(app: &AppHandle) -> Saved {
    file(app)
        .and_then(|path| fs::read(path).ok())
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_default()
}

pub fn save(app: &AppHandle, saved: &Saved) -> Result<(), String> {
    let path = file(app).ok_or("The app has no folder for its settings.")?;
    let write = || -> std::io::Result<()> {
        fs::create_dir_all(path.parent().expect("a file in a folder"))?;
        // Whole or not at all: written beside it, then moved over it.
        let partial = path.with_extension("json.partial");
        fs::write(&partial, serde_json::to_vec_pretty(saved)?)?;
        fs::rename(partial, &path)
    };
    write().map_err(|error| format!("The libraries could not be saved: {error}"))
}

/// The address someone typed as a library's: https unless they wrote
/// another scheme, no query, no trailing slash.
pub fn address(typed: &str) -> Result<Url, String> {
    let typed = typed.trim();
    if typed.is_empty() {
        return Err("Type the address of a paperus server.".into());
    }
    let full = if typed.contains("://") {
        typed.to_owned()
    } else {
        format!("https://{typed}")
    };
    let mut url = Url::parse(&full).map_err(|_| format!("{typed} is not an address."))?;
    if !matches!(url.scheme(), "https" | "http") || url.host_str().is_none() {
        return Err(format!("{typed} is not a web address."));
    }
    url.set_query(None);
    url.set_fragment(None);
    let path = url.path().trim_end_matches('/').to_owned();
    url.set_path(&path);
    Ok(url)
}

/// The library's address as kept: without the slash a bare host gets.
pub fn key(url: &Url) -> String {
    url.as_str().trim_end_matches('/').to_owned()
}

/// The library a page belongs to (by origin), if any.
pub fn of(app: &AppHandle, url: &Url) -> Option<Library> {
    let origin = url.origin();
    load(app)
        .libraries
        .into_iter()
        .find(|library| Url::parse(&library.url).is_ok_and(|own| own.origin() == origin))
}

/// The website's login cookie (`server/src/paperus/api/deps.py`).
pub const SESSION_COOKIE: &str = "paperus_session";

/// The window's login to the library (its cookie), if logged in. Not on
/// the main thread: reading cookies waits for it. Kept by the app too
/// (`remember_session`): WebKitGTK's cookie functions do not see cookies
/// kept from an earlier run, though the window uses them.
pub fn session(window: &WebviewWindow, library: &Url) -> Option<String> {
    let login = |cookies: Vec<tauri::webview::Cookie<'static>>| {
        cookies
            .into_iter()
            .find(|cookie| {
                cookie.name() == SESSION_COOKIE
                    && cookie.domain().is_none_or(|domain| {
                        Some(domain.trim_start_matches('.')) == library.host_str()
                    })
            })
            .map(|cookie| cookie.value().to_owned())
    };
    let app = window.app_handle();
    match window.cookies_for_url(library.clone()).ok().and_then(login) {
        Some(token) => {
            remember_session(app, library, Some(&token));
            Some(token)
        }
        None => kept_login(app, library),
    }
}

/// Logins kept, as last read or written (the system's store is asked once).
static SESSIONS: Mutex<Option<HashMap<String, String>>> = Mutex::new(None);
/// Whether a login had to go into the file: no system store to keep it.
static IN_FILE: AtomicBool = AtomicBool::new(false);

/// Where logins are kept without a system store: the person's alone.
fn sessions_file(app: &AppHandle) -> Option<PathBuf> {
    Some(app.path().app_data_dir().ok()?.join("sessions.json"))
}

fn file_sessions(app: &AppHandle) -> HashMap<String, String> {
    sessions_file(app)
        .and_then(|path| fs::read(path).ok())
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_default()
}

fn save_file_sessions(app: &AppHandle, kept: &HashMap<String, String>) {
    let Some(path) = sessions_file(app) else {
        return;
    };
    if kept.is_empty() {
        let _ = fs::remove_file(&path);
        return;
    }
    if let Some(folder) = path.parent() {
        let _ = fs::create_dir_all(folder);
    }
    if let Ok(bytes) = serde_json::to_vec(kept) {
        let _ = fs::write(&path, bytes);
        // Only for the person themselves.
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = fs::set_permissions(&path, fs::Permissions::from_mode(0o600));
        }
    }
}

/// The system's store of logins (Keychain, Windows' Credential Manager,
/// the Secret Service: GNOME Keyring, KWallet), one entry per library;
/// ``work`` with it, in time: a locked keyring may ask to be unlocked, and
/// unanswered (nobody at the screen) the file serves instead.
fn with_system_store<T: Send + 'static>(
    library: &Url,
    work: impl FnOnce(keyring::Entry) -> Option<T> + Send + 'static,
) -> Option<T> {
    let name = key(library);
    let (done, answer) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let found = keyring::Entry::new("paperus", &name).ok().and_then(work);
        let _ = done.send(found);
    });
    answer.recv_timeout(Duration::from_secs(5)).ok().flatten()
}

/// The app's login to a library, kept from before: in the system's store,
/// else in the file.
pub fn kept_login(app: &AppHandle, library: &Url) -> Option<String> {
    let mut sessions = SESSIONS.lock().ok()?;
    let known = sessions.get_or_insert_with(HashMap::new);
    if let Some(token) = known.get(&key(library)) {
        return Some(token.clone());
    }
    let token = with_system_store(library, |entry| entry.get_password().ok())
        .or_else(|| file_sessions(app).remove(&key(library)));
    let token = token?;
    known.insert(key(library), token.clone());
    Some(token)
}

/// Keep the app's login to a library (``None``: forget it, as when the
/// library no longer takes it): in the system's store where there is one,
/// else in a file of the person's alone.
pub fn remember_session(app: &AppHandle, library: &Url, token: Option<&str>) {
    let Ok(mut sessions) = SESSIONS.lock() else {
        return;
    };
    let known = sessions.get_or_insert_with(HashMap::new);
    if known.get(&key(library)).map(String::as_str) == token {
        return;
    }
    let mut in_file = file_sessions(app);
    match token {
        Some(token) => {
            known.insert(key(library), token.to_owned());
            let secret = token.to_owned();
            let kept =
                with_system_store(library, move |entry| entry.set_password(&secret).ok()).is_some();
            eprintln!(
                "login to {}: kept in {}",
                key(library),
                if kept {
                    "the system's store"
                } else {
                    "the file"
                }
            );
            if kept {
                in_file.remove(&key(library));
            } else {
                IN_FILE.store(true, Ordering::Relaxed);
                in_file.insert(key(library), token.to_owned());
            }
        }
        None => {
            eprintln!("login to {}: forgotten", key(library));
            known.remove(&key(library));
            with_system_store(library, |entry| entry.delete_credential().ok());
            in_file.remove(&key(library));
        }
    }
    save_file_sessions(app, &in_file);
}

/// Whether logins are kept in the app's file, there being no system store.
pub fn logins_in_file(app: &AppHandle) -> bool {
    IN_FILE.load(Ordering::Relaxed) || !file_sessions(app).is_empty()
}

/// For talking to libraries. Certificates are checked as the system does
/// (so also a university's own authority, as its browsers trust it).
pub fn agent() -> ureq::Agent {
    ureq::Agent::config_builder()
        .timeout_global(Some(Duration::from_secs(15)))
        .http_status_as_error(false)
        .tls_config(
            ureq::tls::TlsConfig::builder()
                .root_certs(ureq::tls::RootCerts::PlatformVerifier)
                .build(),
        )
        .build()
        .into()
}

/// For downloading the library on this computer's parts: as long as it
/// takes, but giving up on a connection that stays silent.
pub fn agent_for_downloads() -> ureq::Agent {
    agent_receiving_for(Duration::from_secs(60))
}

/// For a stream kept open (live signals): one connection for at most ten
/// minutes, then another (one gone quiet is not waited on forever).
pub fn agent_for_streams() -> ureq::Agent {
    agent_receiving_for(Duration::from_secs(600))
}

fn agent_receiving_for(body: Duration) -> ureq::Agent {
    ureq::Agent::config_builder()
        .timeout_connect(Some(Duration::from_secs(30)))
        .timeout_recv_body(Some(body))
        .http_status_as_error(false)
        .tls_config(
            ureq::tls::TlsConfig::builder()
                .root_certs(ureq::tls::RootCerts::PlatformVerifier)
                .build(),
        )
        .build()
        .into()
}

/// Whether a paperus answers there: its public list of login methods is
/// one only paperus gives.
pub fn check(url: &Url) -> Result<(), String> {
    let host = url.host_str().unwrap_or_default();
    let agent = agent();
    let mut response = agent
        .get(format!("{}/api/auth/methods", key(url)))
        .header("Accept", "application/json")
        .call()
        .map_err(|error| match error {
            // A server without https (on one's own computer, say).
            ureq::Error::Tls(_) | ureq::Error::Rustls(_) if url.scheme() == "https" => {
                no_https(host)
            }
            ureq::Error::Io(ref io)
                if url.scheme() == "https" && io.kind() == std::io::ErrorKind::InvalidData =>
            {
                no_https(host)
            }
            error => format!("{host} could not be reached: {error}."),
        })?;
    let not_paperus = || format!("{host} answers, but no paperus is there.");
    if !response.status().is_success() {
        return Err(not_paperus());
    }
    let methods: serde_json::Value = response.body_mut().read_json().map_err(|_| not_paperus())?;
    if methods.get("password").is_some_and(|v| v.is_boolean()) {
        Ok(())
    } else {
        Err(not_paperus())
    }
}

fn no_https(host: &str) -> String {
    format!(
        "{host} has no secure connection (https). If it is served without, \
         type its address with http:// in front."
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn addresses_are_https_without_a_trailing_slash() {
        let url = address(" paperus.example.org/ ").unwrap();
        assert_eq!(key(&url), "https://paperus.example.org");
        let url = address("http://localhost:8000/library/?a=1#b").unwrap();
        assert_eq!(key(&url), "http://localhost:8000/library");
        assert!(address("").is_err());
        assert!(address("ftp://example.org").is_err());
        assert!(address("javascript:alert(1)").is_err());
    }
}
