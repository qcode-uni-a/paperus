//! Logging in to a library in the system's browser, where identity
//! providers allow it (some refuse a window inside an app) and where one
//! may be logged in already (docs/apps.md). The app registers as an OAuth
//! client of the library, the person confirms on its page `/app-login`, the
//! browser brings a one-time code back to the app on a loopback address,
//! and the app trades it, with its PKCE verifier, for a session: the
//! website's own login cookie, set in the app's windows.

use std::{
    io::{BufRead, BufReader, Write},
    net::{TcpListener, TcpStream},
    thread,
    time::{Duration, Instant},
};

use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use tauri::{
    AppHandle, Manager, Url,
    webview::{
        Cookie,
        cookie::{SameSite, time},
    },
};
use tauri_plugin_opener::OpenerExt;

use crate::libraries;

/// How long the browser has to come back.
const WAIT: Duration = Duration::from_secs(10 * 60);

/// Log the library shown in window ``label`` in, in the browser; back at
/// ``next`` (a path on it) when done. Problems are shown in the window.
pub fn start(app: AppHandle, label: String, next: String) {
    thread::spawn(move || {
        let Some(window) = app.get_webview_window(&label) else {
            return;
        };
        let Some(library) = window
            .url()
            .ok()
            .and_then(|url| libraries::of(&app, &url))
            .and_then(|library| Url::parse(&library.url).ok())
        else {
            return;
        };
        let outcome = log_in(&app, &library);
        match outcome {
            Ok(Some(session)) => {
                let set = window.set_cookie(cookie(&library, session.token, session.max_age));
                let target = library.join(&next).unwrap_or(library);
                if set.is_ok() {
                    let _ = window.navigate(target);
                }
                let _ = window.set_focus();
            }
            // Cancelled in the browser, or never came back.
            Ok(None) => {}
            Err(message) => {
                let _ = window.set_focus();
                let _ = window.eval(format!(
                    "alert({})",
                    serde_json::to_string(&message).unwrap_or_default()
                ));
            }
        }
    });
}

#[derive(Deserialize)]
struct Session {
    token: String,
    max_age: i64,
}

fn log_in(app: &AppHandle, library: &Url) -> Result<Option<Session>, String> {
    let base = libraries::key(library);
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|error| error.to_string())?;
    let port = listener.local_addr().map_err(|e| e.to_string())?.port();
    let redirect = format!("http://127.0.0.1:{port}/done");

    // Registered anew each time: a client nobody connected is removed
    // after a day (server/src/paperus/oauth.py).
    let registered: serde_json::Value = libraries::agent()
        .post(format!("{base}/api/oauth/register"))
        .send_json(serde_json::json!({
            "client_name": "the paperus app",
            "redirect_uris": ["http://127.0.0.1/done"],
        }))
        .map_err(|error| format!("{base} could not be reached: {error}."))
        .and_then(answer::<serde_json::Value>)?;
    let client_id = registered["client_id"]
        .as_str()
        .ok_or("The server did not register the app.")?
        .to_owned();

    let verifier = random(32);
    let challenge = URL_SAFE_NO_PAD.encode(Sha256::digest(verifier.as_bytes()));
    let state = random(16);
    let mut page = library
        .join("/app-login")
        .map_err(|error| error.to_string())?;
    page.query_pairs_mut()
        .append_pair("client_id", &client_id)
        .append_pair("redirect_uri", &redirect)
        .append_pair("code_challenge", &challenge)
        .append_pair("state", &state);
    app.opener()
        .open_url(page.as_str(), None::<&str>)
        .map_err(|error| format!("The browser did not open: {error}."))?;

    let Some(code) = wait_for_code(&listener, &state)? else {
        return Ok(None);
    };
    let session = libraries::agent()
        .post(format!("{base}/api/oauth/app-session"))
        .send_json(serde_json::json!({
            "client_id": client_id,
            "code": code,
            "redirect_uri": redirect,
            "code_verifier": verifier,
        }))
        .map_err(|error| format!("{base} could not be reached: {error}."))
        .and_then(answer::<Session>)?;
    Ok(Some(session))
}

/// The server's answer, or what it said went wrong.
fn answer<T: serde::de::DeserializeOwned>(
    mut response: ureq::http::Response<ureq::Body>,
) -> Result<T, String> {
    let status = response.status();
    let body = response.body_mut();
    if !status.is_success() {
        let said = body
            .read_json::<serde_json::Value>()
            .ok()
            .and_then(|error| {
                let text = error.get("error_description").or(error.get("detail"))?;
                Some(text.as_str()?.to_owned())
            })
            .unwrap_or_else(|| status.to_string());
        return Err(format!("Logging in did not work: {said}"));
    }
    body.read_json()
        .map_err(|error| format!("Logging in did not work: {error}."))
}

/// ``bytes`` random bytes, as URL-safe text.
pub fn random(bytes: usize) -> String {
    let mut buffer = vec![0; bytes];
    getrandom::fill(&mut buffer).expect("the system's randomness");
    URL_SAFE_NO_PAD.encode(buffer)
}

/// The code the browser brings back (None: refused, or no answer in time).
/// Only a request with the state the app sent counts: no other page can
/// slip the app a code of its own.
fn wait_for_code(listener: &TcpListener, state: &str) -> Result<Option<String>, String> {
    listener
        .set_nonblocking(true)
        .map_err(|error| error.to_string())?;
    let until = Instant::now() + WAIT;
    while Instant::now() < until {
        match listener.accept() {
            Ok((stream, _)) => {
                if let Some(answer) = answered(stream, state) {
                    return Ok(answer);
                }
            }
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                thread::sleep(Duration::from_millis(200));
            }
            Err(error) => return Err(error.to_string()),
        }
    }
    Ok(None)
}

/// The browser's request, answered with a page to close; ``None`` if it
/// was not the one the app waits for.
fn answered(mut stream: TcpStream, state: &str) -> Option<Option<String>> {
    stream.set_nonblocking(false).ok()?;
    stream.set_read_timeout(Some(Duration::from_secs(5))).ok()?;
    let mut line = String::new();
    BufReader::new(&stream).read_line(&mut line).ok()?;
    let answer = parse(&line, state);
    let (status, text) = match &answer {
        Some(Some(_)) => (
            "200 OK",
            "You are logged in to the paperus app. Close this tab and go back to the app.",
        ),
        Some(None) => (
            "200 OK",
            "The app was not logged in. You can close this tab.",
        ),
        None => ("404 Not Found", "Nothing here."),
    };
    let body = format!(
        "<!doctype html><meta charset=utf-8><title>paperus</title>\
         <p style=\"font:1.1rem system-ui;margin:20vh auto;max-width:30rem\">{text}</p>"
    );
    let _ = write!(
        stream,
        "HTTP/1.1 {status}\r\nContent-Type: text/html; charset=utf-8\r\n\
         Content-Length: {}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    answer
}

/// The request line ``GET /done?code=…&state=… HTTP/1.1``: ``Some(code)``
/// when allowed, ``Some(None)`` when refused, ``None`` if not for the app.
fn parse(line: &str, state: &str) -> Option<Option<String>> {
    let mut parts = line.split_whitespace();
    let (method, target) = (parts.next()?, parts.next()?);
    let url = Url::parse("http://127.0.0.1").ok()?.join(target).ok()?;
    if method != "GET" || url.path() != "/done" {
        return None;
    }
    let value = |name: &str| {
        url.query_pairs()
            .find(|(key, _)| key == name)
            .map(|(_, value)| value.into_owned())
    };
    if value("state").as_deref() != Some(state) {
        return None;
    }
    Some(value("code"))
}

/// A session as the website's own login cookie for the library.
pub fn cookie(library: &Url, token: String, max_age: i64) -> Cookie<'static> {
    Cookie::build((libraries::SESSION_COOKIE, token))
        .domain(library.host_str().unwrap_or_default().to_owned())
        .path("/")
        .http_only(true)
        .secure(library.scheme() == "https")
        .same_site(SameSite::Lax)
        .max_age(time::Duration::seconds(max_age))
        .build()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_the_browser_coming_back_counts() {
        assert_eq!(
            parse("GET /done?code=abc&state=s1 HTTP/1.1\r\n", "s1"),
            Some(Some("abc".into()))
        );
        // Refused in the browser.
        assert_eq!(
            parse("GET /done?error=access_denied&state=s1 HTTP/1.1", "s1"),
            Some(None)
        );
        // Another state, another path, another method: not the answer.
        assert_eq!(parse("GET /done?code=abc&state=s2 HTTP/1.1", "s1"), None);
        assert_eq!(parse("GET /favicon.ico HTTP/1.1", "s1"), None);
        assert_eq!(parse("POST /done?code=abc&state=s1 HTTP/1.1", "s1"), None);
        assert_eq!(parse("", "s1"), None);
    }

    #[test]
    fn the_cookie_is_the_websites_own() {
        let library = Url::parse("https://paperus.example.org/").unwrap();
        let cookie = cookie(&library, "t".into(), 60);
        assert_eq!(cookie.name(), "paperus_session");
        assert_eq!(cookie.domain(), Some("paperus.example.org"));
        assert_eq!(cookie.secure(), Some(true));
        assert_eq!(cookie.http_only(), Some(true));
    }

    #[test]
    fn verifiers_are_long_enough_for_pkce() {
        // RFC 7636: 43 to 128 characters.
        assert_eq!(random(32).len(), 43);
        assert_ne!(random(32), random(32));
    }
}
