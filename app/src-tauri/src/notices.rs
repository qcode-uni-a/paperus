//! The bell's notifications as the system's (docs/apps.md): papers others
//! add to one's groups, published versions found. Asked for every minute,
//! with the window's login; only those that come while the app runs, and
//! not while its window is in front (the bell shows them there).

use std::{collections::HashMap, thread, time::Duration};

use serde::Deserialize;
use tauri::{AppHandle, Manager, Url};
use tauri_plugin_notification::NotificationExt;

use crate::{MAIN, libraries};

const EVERY: Duration = Duration::from_secs(60);

#[derive(Deserialize)]
struct Notifications {
    notifications: Vec<Notice>,
}

#[derive(Deserialize)]
struct Notice {
    id: i64,
    kind: String,
    data: serde_json::Value,
    read: bool,
}

pub fn start(app: AppHandle) {
    thread::spawn(move || {
        // The newest notification seen, per library: newer ones are new.
        let mut seen: HashMap<String, i64> = HashMap::new();
        loop {
            thread::sleep(EVERY);
            let _ = look(&app, &mut seen);
        }
    });
}

fn look(app: &AppHandle, seen: &mut HashMap<String, i64>) -> Option<()> {
    let window = app.get_webview_window(MAIN)?;
    let library = libraries::of(app, &window.url().ok()?)?;
    let url = Url::parse(&library.url).ok()?;
    let token = libraries::session(&window, &url)?;
    let found: Notifications = libraries::agent()
        .get(format!("{}/api/me/notifications?limit=10", library.url))
        .header("Cookie", &format!("{}={token}", libraries::SESSION_COOKIE))
        .call()
        .ok()
        .filter(|response| response.status().is_success())?
        .body_mut()
        .read_json()
        .ok()?;
    let newest = found.notifications.iter().map(|n| n.id).max().unwrap_or(0);
    let Some(&before) = seen.get(&library.url) else {
        // The first look: what is there already is no news.
        seen.insert(library.url, newest);
        return Some(());
    };
    seen.insert(library.url, newest.max(before));
    if window.is_focused().unwrap_or(false) {
        return Some(());
    }
    for notice in found.notifications.iter().rev() {
        if notice.id > before && !notice.read {
            let _ = app
                .notification()
                .builder()
                .title(&library.name)
                .body(text(notice))
                .show();
        }
    }
    Some(())
}

/// What it says, as the bell says it (web/src/lib/NotificationBell.svelte).
fn text(notice: &Notice) -> String {
    let field = |name: &str| match &notice.data[name] {
        serde_json::Value::String(text) if !text.is_empty() => Some(text.clone()),
        serde_json::Value::Number(number) => Some(number.to_string()),
        _ => None,
    };
    let title = field("title");
    match notice.kind.as_str() {
        "added" => {
            let actor = field("actor").unwrap_or_else(|| "Someone".into());
            let group = field("group").unwrap_or_else(|| "a group".into());
            match notice.data["count"].as_i64().unwrap_or(1) {
                1 => format!(
                    "{actor} added “{}” to {group}",
                    title.unwrap_or_else(|| "a paper".into())
                ),
                count => format!("{actor} added {count} papers to {group}"),
            }
        }
        "published" => {
            let year = field("year").map(|year| format!("({year})"));
            let place = [field("journal"), year]
                .into_iter()
                .flatten()
                .collect::<Vec<_>>()
                .join(" ");
            let place = if place.is_empty() {
                String::new()
            } else {
                format!(" in {place}")
            };
            format!("Published{place}: “{}”", title.unwrap_or_default())
        }
        other => title.unwrap_or_else(|| other.to_owned()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn notice(kind: &str, data: serde_json::Value) -> Notice {
        Notice {
            id: 1,
            kind: kind.into(),
            data,
            read: false,
        }
    }

    #[test]
    fn worded_as_the_bell_words_them() {
        let one = serde_json::json!({"actor": "Ada", "group": "Optics lab", "count": 1, "title": "On light"});
        assert_eq!(
            text(&notice("added", one)),
            "Ada added “On light” to Optics lab"
        );
        let many = serde_json::json!({"actor": "Ada", "group": "Optics lab", "count": 12});
        assert_eq!(
            text(&notice("added", many)),
            "Ada added 12 papers to Optics lab"
        );
        let published = serde_json::json!({"title": "On light", "journal": "Nature", "year": 2026});
        assert_eq!(
            text(&notice("published", published)),
            "Published in Nature (2026): “On light”"
        );
        let bare = serde_json::json!({"title": "On light"});
        assert_eq!(text(&notice("published", bare)), "Published: “On light”");
    }
}
