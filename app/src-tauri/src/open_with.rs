//! "Open with → paperus" for PDFs (docs/apps.md): each file is added to the
//! library shown in the app's window, as the website's upload does, with
//! the window's login; then its paper is shown.

use std::{
    fs,
    path::{Path, PathBuf},
    sync::{
        Mutex,
        atomic::{AtomicBool, Ordering},
    },
    thread,
};

use serde::Deserialize;
use tauri::{AppHandle, Manager, Url, WebviewWindow};

use crate::{MAIN, libraries};

/// The website's login cookie (`server/src/paperus/api/deps.py`).
const SESSION_COOKIE: &str = "paperus_session";

#[derive(Deserialize)]
struct Uploaded {
    item_id: String,
}

/// Files given before the window had a page, and whether it has one.
static WAITING: Mutex<Vec<PathBuf>> = Mutex::new(Vec::new());
static LOADED: AtomicBool = AtomicBool::new(false);

/// The files given to the app (on starting it, or while it runs); added
/// once the window shows its first page (whose login they need).
pub fn open(app: &AppHandle, files: Vec<PathBuf>) {
    let files: Vec<PathBuf> = files.into_iter().filter(|path| path.is_file()).collect();
    if files.is_empty() {
        return;
    }
    let mut waiting = WAITING.lock().expect("not poisoned");
    if LOADED.load(Ordering::SeqCst) {
        drop(waiting);
        add_soon(app, files);
    } else {
        waiting.extend(files);
    }
}

/// The window's first page is there: the files given before, added.
pub fn loaded(app: &AppHandle) {
    let mut waiting = WAITING.lock().expect("not poisoned");
    if !LOADED.swap(true, Ordering::SeqCst) {
        let files = std::mem::take(&mut *waiting);
        drop(waiting);
        if !files.is_empty() {
            add_soon(app, files);
        }
    }
}

fn add_soon(app: &AppHandle, files: Vec<PathBuf>) {
    let app = app.clone();
    // Away from the main thread: reading cookies waits for it.
    thread::spawn(move || {
        let Some(window) = app.get_webview_window(MAIN) else {
            return;
        };
        let _ = window.unminimize();
        let _ = window.set_focus();
        if let Err(message) = add(&app, &window, &files) {
            let _ = window.eval(format!(
                "alert({})",
                serde_json::to_string(&message).unwrap_or_default()
            ));
        }
    });
}

/// Files from the command line (Linux and Windows hand them over so).
pub fn files_in(arguments: &[String]) -> Vec<PathBuf> {
    arguments
        .iter()
        .skip(1)
        .filter(|argument| !argument.starts_with('-'))
        .map(PathBuf::from)
        .collect()
}

fn add(app: &AppHandle, window: &WebviewWindow, files: &[PathBuf]) -> Result<(), String> {
    let shown = window.url().map_err(|error| error.to_string())?;
    let library = libraries::of(app, &shown)
        .and_then(|library| Url::parse(&library.url).ok())
        .ok_or("Open a library first, then the file again.")?;
    let session = window
        .cookies_for_url(library.clone())
        .map_err(|error| error.to_string())?
        .into_iter()
        .find(|cookie| cookie.name() == SESSION_COOKIE)
        .map(|cookie| cookie.value().to_owned())
        .ok_or("Log in first, then open the file again.")?;
    let mut last = None;
    for file in files {
        last = Some(upload(&library, &session, file)?);
    }
    let target = match (files.len(), last) {
        (1, Some(item)) => format!("/items/{item}"),
        _ => "/".to_owned(),
    };
    let _ = window.navigate(library.join(&target).map_err(|error| error.to_string())?);
    Ok(())
}

fn upload(library: &Url, session: &str, file: &Path) -> Result<String, String> {
    let name = file
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_else(|| "file.pdf".into());
    let bytes = fs::read(file).map_err(|error| format!("{name} could not be read: {error}."))?;
    let (content_type, body) = multipart(&name, &bytes);
    let mut response = libraries::agent()
        .post(format!("{}/api/uploads", libraries::key(library)))
        .header("Cookie", &format!("{SESSION_COOKIE}={session}"))
        .header("Content-Type", &content_type)
        .send(&body[..])
        .map_err(|error| format!("{name} could not be added: {error}."))?;
    let status = response.status();
    if status == 401 {
        return Err("Log in again, then open the file again.".into());
    }
    if status == 413 {
        return Err(format!("{name} is too large for this library."));
    }
    if !status.is_success() {
        let said = response
            .body_mut()
            .read_json::<serde_json::Value>()
            .ok()
            .and_then(|error| Some(error.get("detail")?.as_str()?.to_owned()))
            .unwrap_or_else(|| status.to_string());
        return Err(format!("{name} could not be added: {said}"));
    }
    let uploaded: Uploaded = response
        .body_mut()
        .read_json()
        .map_err(|error| format!("{name}: {error}"))?;
    Ok(uploaded.item_id)
}

/// The form the website's upload sends: the file as ``upload``.
fn multipart(name: &str, bytes: &[u8]) -> (String, Vec<u8>) {
    let boundary = format!("paperus-{:016x}", rand_u64());
    // Quotes and line breaks would end the header early.
    let name: String = name
        .chars()
        .map(|c| {
            if matches!(c, '"' | '\r' | '\n') {
                '_'
            } else {
                c
            }
        })
        .collect();
    let mut body = format!(
        "--{boundary}\r\nContent-Disposition: form-data; name=\"upload\"; filename=\"{name}\"\r\n\
         Content-Type: application/octet-stream\r\n\r\n"
    )
    .into_bytes();
    body.extend_from_slice(bytes);
    body.extend_from_slice(format!("\r\n--{boundary}--\r\n").as_bytes());
    (format!("multipart/form-data; boundary={boundary}"), body)
}

fn rand_u64() -> u64 {
    let mut bytes = [0; 8];
    getrandom::fill(&mut bytes).expect("the system's randomness");
    u64::from_le_bytes(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn files_come_after_the_program() {
        let arguments = ["paperus-app", "/home/ada/a.pdf", "--flag", "b.pdf"].map(String::from);
        assert_eq!(
            files_in(&arguments),
            [PathBuf::from("/home/ada/a.pdf"), PathBuf::from("b.pdf")]
        );
    }

    #[test]
    fn the_form_holds_the_file_under_its_name() {
        let (content_type, body) = multipart("On \"x\".pdf", b"%PDF-1.7");
        let boundary = content_type.split("boundary=").nth(1).unwrap();
        let body = String::from_utf8(body).unwrap();
        assert!(body.starts_with(&format!("--{boundary}\r\n")));
        assert!(body.contains("name=\"upload\"; filename=\"On _x_.pdf\""));
        assert!(body.contains("\r\n\r\n%PDF-1.7\r\n"));
        assert!(body.ends_with(&format!("--{boundary}--\r\n")));
    }
}
