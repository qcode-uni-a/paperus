//! The library's website as last loaded (`/api/web-files`): kept to run
//! offline, so offline it is the same version as the server it synced
//! with. Only changed files are downloaded; the new copy replaces the old
//! at once.

use std::{
    fs,
    path::{Component, Path, PathBuf},
};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::http::Response;

use crate::libraries;

const LISTING: &str = "listing.json";

#[derive(Deserialize, Serialize, PartialEq)]
struct Listing {
    fallback: String,
    files: Vec<WebFile>,
}

#[derive(Deserialize, Serialize, PartialEq)]
struct WebFile {
    path: String,
    sha256: String,
    size: u64,
}

fn current(folder: &Path) -> PathBuf {
    folder.join("site")
}

fn listing(site: &Path) -> Option<Listing> {
    serde_json::from_slice(&fs::read(site.join(LISTING)).ok()?).ok()
}

/// Whether a copy of the website is kept.
pub fn has_copy(folder: &Path) -> bool {
    listing(&current(folder)).is_some()
}

/// A path inside the copy, or None if it would lead out of it.
fn inside(site: &Path, path: &str) -> Option<PathBuf> {
    let relative = Path::new(path.trim_start_matches('/'));
    relative
        .components()
        .all(|part| matches!(part, Component::Normal(_)))
        .then(|| site.join(relative))
}

fn sha256(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

/// Bring the copy in ``folder`` up to the website at ``url``.
pub fn copy(url: &str, folder: &Path) -> Result<(), String> {
    let mut response = libraries::agent()
        .get(format!("{url}/api/web-files"))
        .call()
        .map_err(|error| error.to_string())?;
    if !response.status().is_success() {
        // A server without its website (in development): nothing to copy.
        return Ok(());
    }
    let found: Listing = response
        .body_mut()
        .read_json()
        .map_err(|error| error.to_string())?;
    let site = current(folder);
    if listing(&site).as_ref() == Some(&found) {
        return Ok(());
    }
    let next = folder.join("site.next");
    let _ = fs::remove_dir_all(&next);
    let agent = libraries::agent_for_downloads();
    for file in &found.files {
        // Compressed twins are for the server's own answers.
        if file.path.ends_with(".br") || file.path.ends_with(".gz") {
            continue;
        }
        let (Some(target), Some(old)) = (inside(&next, &file.path), inside(&site, &file.path))
        else {
            continue;
        };
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        let kept = fs::read(&old)
            .ok()
            .filter(|bytes| sha256(bytes) == file.sha256);
        let bytes = match kept {
            Some(bytes) => bytes,
            None => {
                let address = url::Url::parse(url)
                    .and_then(|base| base.join(&file.path))
                    .map_err(|error| error.to_string())?;
                let bytes = agent
                    .get(address.as_str())
                    .call()
                    .map_err(|error| error.to_string())?
                    .body_mut()
                    .with_config()
                    .limit(1 << 28)
                    .read_to_vec()
                    .map_err(|error| error.to_string())?;
                if sha256(&bytes) != file.sha256 {
                    // Changed while copying: next time.
                    return Err(format!("{}: changed", file.path));
                }
                bytes
            }
        };
        fs::write(&target, bytes).map_err(|error| error.to_string())?;
    }
    let text = serde_json::to_vec(&found).map_err(|error| error.to_string())?;
    fs::write(next.join(LISTING), text).map_err(|error| error.to_string())?;
    let old = folder.join("site.old");
    let _ = fs::remove_dir_all(&old);
    if site.exists() {
        fs::rename(&site, &old).map_err(|error| error.to_string())?;
    }
    fs::rename(&next, &site).map_err(|error| error.to_string())?;
    let _ = fs::remove_dir_all(&old);
    Ok(())
}

/// What a file is, from its name.
fn media_type(path: &Path) -> &'static str {
    match path.extension().and_then(|extension| extension.to_str()) {
        Some("html") => "text/html; charset=utf-8",
        Some("js" | "mjs") => "text/javascript; charset=utf-8",
        Some("css") => "text/css; charset=utf-8",
        Some("json" | "webmanifest") => "application/json",
        Some("wasm") => "application/wasm",
        Some("svg") => "image/svg+xml",
        Some("png") => "image/png",
        Some("ico") => "image/x-icon",
        Some("woff2") => "font/woff2",
        Some("woff") => "font/woff",
        Some("ttf") => "font/ttf",
        Some("txt") => "text/plain; charset=utf-8",
        _ => "application/octet-stream",
    }
}

/// A file of the copy, else (a page of the website) its entry page.
pub fn file(folder: &Path, path: &str) -> Response<Vec<u8>> {
    let site = current(folder);
    let fallback = listing(&site).map_or_else(|| "200.html".to_owned(), |found| found.fallback);
    let found = inside(&site, path)
        .filter(|file| file.is_file() && !file.ends_with(LISTING))
        .or_else(|| inside(&site, &fallback));
    match found.and_then(|file| Some((fs::read(&file).ok()?, file))) {
        Some((bytes, file)) => Response::builder()
            .header("Content-Type", media_type(&file))
            .body(bytes),
        None => Response::builder().status(404).body(Vec::new()),
    }
    .expect("a response")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_inside_the_copy() {
        let site = Path::new("/copy");
        assert_eq!(
            inside(site, "/_app/immutable/app.js"),
            Some(PathBuf::from("/copy/_app/immutable/app.js"))
        );
        assert_eq!(inside(site, "/../secret"), None);
        assert_eq!(inside(site, "/_app/../../secret"), None);
    }

    #[test]
    fn files_and_pages() {
        let folder = std::env::temp_dir().join(format!("paperus-site-{}", std::process::id()));
        let site = current(&folder);
        fs::create_dir_all(site.join("_app")).unwrap();
        fs::write(site.join("200.html"), "<html>app</html>").unwrap();
        fs::write(site.join("_app/app.js"), "1").unwrap();
        let listed = Listing {
            fallback: "200.html".into(),
            files: vec![],
        };
        fs::write(site.join(LISTING), serde_json::to_vec(&listed).unwrap()).unwrap();
        assert!(has_copy(&folder));
        let script = file(&folder, "/_app/app.js");
        assert_eq!(script.body(), b"1");
        assert_eq!(
            script.headers()["Content-Type"],
            "text/javascript; charset=utf-8"
        );
        // A page of the website, and what is not a file: the entry page.
        assert_eq!(file(&folder, "/items/123").body(), b"<html>app</html>");
        assert_eq!(file(&folder, "/listing.json").body(), b"<html>app</html>");
        fs::remove_dir_all(&folder).unwrap();
    }
}
