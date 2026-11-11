//! The libraries the app knows (paperus servers), kept in the app's config
//! folder, and the check that an address is one.

use std::{fs, path::PathBuf, time::Duration};

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
/// the main thread: reading cookies waits for it.
pub fn session(window: &WebviewWindow, library: &Url) -> Option<String> {
    window
        .cookies_for_url(library.clone())
        .ok()?
        .into_iter()
        .find(|cookie| cookie.name() == SESSION_COOKIE)
        .map(|cookie| cookie.value().to_owned())
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
    ureq::Agent::config_builder()
        .timeout_connect(Some(Duration::from_secs(30)))
        .timeout_recv_body(Some(Duration::from_secs(60)))
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
