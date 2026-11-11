//! Changes made offline (docs/apps.md, "Pushing"): applied to the copy at
//! once, answered as the server would, and queued to send when the library
//! is back (`super::push`): annotations made, changed, removed; where one
//! stopped reading and what one opened; notes written or edited. New
//! records get their ID here (a UUIDv7, as the server makes them), so the
//! server keeps it; edits carry the version they started from, so the
//! server refuses them if it changed meanwhile, nothing overwritten.

use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{Map, Value, json};
use tauri::http::{Response, StatusCode};

use super::store::{Queued, Store};

/// A new ID, as the server makes them (UUIDv7: the time, then chance).
pub fn new_id() -> String {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |since| since.as_millis() as u64);
    let mut bytes = [0u8; 16];
    bytes[..6].copy_from_slice(&millis.to_be_bytes()[2..]);
    getrandom::fill(&mut bytes[6..]).expect("the system's randomness");
    bytes[6] = 0x70 | (bytes[6] & 0x0f);
    bytes[8] = 0x80 | (bytes[8] & 0x3f);
    let hex: String = bytes.iter().map(|byte| format!("{byte:02x}")).collect();
    format!(
        "{}-{}-{}-{}-{}",
        &hex[..8],
        &hex[8..12],
        &hex[12..16],
        &hex[16..20],
        &hex[20..]
    )
}

/// Now, as the server writes times.
fn now() -> String {
    let since = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    let days = (since.as_secs() / 86_400) as i64;
    let seconds = since.as_secs() % 86_400;
    // The civil date from days since 1970 (Howard Hinnant's algorithm).
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let day_of_era = z.rem_euclid(146_097);
    let year_of_era =
        (day_of_era - day_of_era / 1460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_index = (5 * day_of_year + 2) / 153;
    let day = day_of_year - (153 * month_index + 2) / 5 + 1;
    let month = if month_index < 10 {
        month_index + 3
    } else {
        month_index - 9
    };
    let year = year_of_era + era * 400 + i64::from(month <= 2);
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}.{:06}Z",
        seconds / 3600,
        seconds % 3600 / 60,
        seconds % 60,
        since.subsec_micros()
    )
}

fn json_response(status: u16, body: &Value) -> Response<Vec<u8>> {
    Response::builder()
        .status(status)
        .header("Content-Type", "application/json")
        .body(body.to_string().into_bytes())
        .expect("a response")
}

fn no_content() -> Response<Vec<u8>> {
    Response::builder()
        .status(StatusCode::NO_CONTENT)
        .body(Vec::new())
        .expect("a response")
}

fn not_found(what: &str) -> Response<Vec<u8>> {
    json_response(404, &json!({"detail": format!("{what} not found")}))
}

/// Who one is, as the copy last saw it: the name annotations are shown with.
fn my_name(store: &Store) -> String {
    store
        .answer("/api/auth/me")
        .and_then(|(_, _, body)| serde_json::from_slice::<Value>(&body).ok())
        .and_then(|me| {
            me["display_name"]
                .as_str()
                .filter(|name| !name.is_empty())
                .or(me["username"].as_str())
                .map(str::to_owned)
        })
        .unwrap_or_default()
}

fn text(record: &Value, field: &str) -> String {
    record[field].as_str().unwrap_or_default().to_owned()
}

/// The paper a file belongs to (of those kept).
fn paper_of_file(store: &Store, file_id: &str) -> Option<Value> {
    store.all("item").into_iter().find(|item| {
        item["files"]
            .as_array()
            .into_iter()
            .flatten()
            .any(|file| text(file, "id") == file_id)
    })
}

/// A change in words, for when it cannot be saved: the paper, the page and
/// what was written.
fn annotation_words(store: &Store, annotation: &Value) -> String {
    let paper = store
        .get("item", &text(annotation, "item_id"))
        .map(|item| text(&item, "title"))
        .unwrap_or_default();
    let page = annotation["page_label"]
        .as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| (annotation["page_index"].as_i64().unwrap_or(0) + 1).to_string());
    let said = [text(annotation, "comment"), text(annotation, "text")]
        .into_iter()
        .find(|words| !words.is_empty())
        .map(|words| format!(": “{words}”"))
        .unwrap_or_default();
    format!("An annotation on “{paper}”, page {page}{said}")
}

/// The note's title: its first line without Markdown marks
/// (`notes.title_of`; the server's own comes with the next sync).
fn title_of(note: &str) -> String {
    note.lines()
        .map(|line| {
            line.trim()
                .trim_start_matches(['#', '>', '-', '*', '+'])
                .replace(['*', '_', '`', '~', '[', ']'], "")
                .trim()
                .to_owned()
        })
        .find(|line| !line.is_empty())
        .map(|line| line.chars().take(300).collect())
        .unwrap_or_default()
}

fn excerpt_of(note: &str) -> String {
    let rest: Vec<&str> = note
        .lines()
        .skip_while(|line| line.trim().is_empty())
        .skip(1)
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .collect();
    let rest = rest.join(" ").replace(['#', '*', '_', '`', '>'], "");
    if rest.chars().count() > 200 {
        format!("{}…", rest.chars().take(200).collect::<String>())
    } else {
        rest
    }
}

/// The website's change ``method`` ``path`` (``body``: JSON), offline.
pub fn change(store: &Store, method: &str, path: &str, body: &[u8]) -> Response<Vec<u8>> {
    let parts: Vec<&str> = path.trim_matches('/').split('/').collect();
    let body: Value = serde_json::from_slice(body).unwrap_or(Value::Null);
    let outcome = match (method, parts.as_slice()) {
        ("POST", ["api", "files", file_id, "annotations"]) => add_annotation(store, file_id, body),
        ("PATCH", ["api", "annotations", id]) => change_annotation(store, id, body),
        ("DELETE", ["api", "annotations", id]) => remove_annotation(store, id),
        ("PUT", ["api", "items", id, "reading"]) => reading(store, id, Some(body)),
        ("POST", ["api", "items", id, "viewed"]) => reading(store, id, None),
        ("POST", ["api", "notes"]) => add_note(store, body),
        ("PATCH", ["api", "notes", id]) => change_note(store, id, body),
        _ => {
            return json_response(
                503,
                &json!({"detail": "Not possible offline: this change needs the library's server."}),
            );
        }
    };
    outcome.unwrap_or_else(|error| json_response(500, &json!({"detail": error.to_string()})))
}

fn add_annotation(
    store: &Store,
    file_id: &str,
    mut body: Value,
) -> rusqlite::Result<Response<Vec<u8>>> {
    let Some(paper) = paper_of_file(store, file_id) else {
        return Ok(not_found("file"));
    };
    let id = body["id"].as_str().map_or_else(new_id, str::to_owned);
    body["id"] = json!(id);
    let at = now();
    let mut annotation = json!({
        "id": id,
        "file_id": file_id,
        "kind": body["kind"],
        "page_index": body["page_index"],
        "page_label": body["page_label"],
        "position": body["position"],
        "color": text(&body, "color").to_lowercase(),
        "text": body["text"],
        "comment": body["comment"],
        "tags": body["tags"].as_array().cloned().unwrap_or_default(),
        "imported": false,
        "mine": true,
        "author": my_name(store),
        "created_at": at,
        "changed_at": at,
        "change": 0,
    });
    if annotation["color"] == "" {
        annotation["color"] = json!("#ffd400");
    }
    let mut kept = annotation.clone();
    kept["item_id"] = paper["id"].clone();
    store.put("annotation", &kept)?;
    store.enqueue(&Queued {
        method: "POST".into(),
        path: format!("/api/files/{file_id}/annotations"),
        body: Some(body.to_string()),
        key: Some(format!("new annotation {id}")),
        what: annotation_words(store, &kept),
        ..Queued::default()
    })?;
    Ok(json_response(201, &annotation))
}

fn change_annotation(store: &Store, id: &str, body: Value) -> rusqlite::Result<Response<Vec<u8>>> {
    let Some(mut kept) = store.get("annotation", id) else {
        return Ok(not_found("annotation"));
    };
    let Value::Object(given) = body else {
        return Ok(json_response(
            422,
            &json!({"detail": "a change is an object"}),
        ));
    };
    for (field, value) in &given {
        kept[field] = match field.as_str() {
            "color" => json!(value.as_str().unwrap_or_default().to_lowercase()),
            "comment" | "text" if value.as_str() == Some("") => Value::Null,
            _ => value.clone(),
        };
    }
    kept["changed_at"] = json!(now());
    store.put("annotation", &kept)?;
    let what = annotation_words(store, &kept);
    // Made offline and not sent yet: the change goes into the making.
    let new = format!("new annotation {id}");
    if let Some(mut making) = store.queued_by_key(&new) {
        let mut sent: Map<String, Value> = making
            .body
            .as_deref()
            .and_then(|body| serde_json::from_str(body).ok())
            .unwrap_or_default();
        sent.extend(given);
        making.body = Some(Value::Object(sent).to_string());
        making.what = what;
        store.enqueue(&making)?;
    } else {
        let key = format!("annotation {id}");
        let mut sent: Map<String, Value> = store
            .queued_by_key(&key)
            .and_then(|queued| serde_json::from_str(queued.body.as_deref()?).ok())
            .unwrap_or_default();
        sent.extend(given);
        let change = kept["change"].as_i64().unwrap_or(0);
        store.enqueue(&Queued {
            method: "PATCH".into(),
            path: format!("/api/annotations/{id}"),
            body: Some(Value::Object(sent).to_string()),
            if_match: (change > 0).then(|| format!("\"{change}\"")),
            key: Some(key),
            what,
            ..Queued::default()
        })?;
    }
    let mut answer = kept;
    if let Some(fields) = answer.as_object_mut() {
        fields.remove("item_id");
    }
    Ok(json_response(200, &answer))
}

fn remove_annotation(store: &Store, id: &str) -> rusqlite::Result<Response<Vec<u8>>> {
    let Some(kept) = store.get("annotation", id) else {
        return Ok(not_found("annotation"));
    };
    store.remove("annotation", id)?;
    // Made offline and not sent yet: nothing to send at all.
    if let Some(making) = store.queued_by_key(&format!("new annotation {id}")) {
        store.dequeue(making.seq)?;
        return Ok(no_content());
    }
    if let Some(changing) = store.queued_by_key(&format!("annotation {id}")) {
        store.dequeue(changing.seq)?;
    }
    store.enqueue(&Queued {
        method: "DELETE".into(),
        path: format!("/api/annotations/{id}"),
        what: format!("Removing {}", annotation_words(store, &kept).to_lowercase()),
        ..Queued::default()
    })?;
    Ok(no_content())
}

/// Where one stopped reading (``place``), or that one opened the paper.
fn reading(store: &Store, id: &str, place: Option<Value>) -> rusqlite::Result<Response<Vec<u8>>> {
    let Some(paper) = store.get("item", id) else {
        return Ok(not_found("item"));
    };
    let mut view = store
        .get("view", id)
        .unwrap_or_else(|| json!({"item_id": id, "reading": null}));
    view["viewed_at"] = json!(now());
    let title = text(&paper, "title");
    let (path, what) = match &place {
        Some(place) => {
            view["reading"] = place.clone();
            (
                format!("/api/items/{id}/reading"),
                format!("Where you stopped reading “{title}”"),
            )
        }
        None => (
            format!("/api/items/{id}/viewed"),
            format!("That you opened “{title}”"),
        ),
    };
    store.put("view", &view)?;
    store.enqueue(&Queued {
        method: if place.is_some() { "PUT" } else { "POST" }.into(),
        key: Some(path.clone()),
        path,
        body: place.map(|place| place.to_string()),
        what,
        ..Queued::default()
    })?;
    Ok(no_content())
}

fn add_note(store: &Store, mut body: Value) -> rusqlite::Result<Response<Vec<u8>>> {
    let id = body["id"].as_str().map_or_else(new_id, str::to_owned);
    body["id"] = json!(id);
    let words = text(&body, "text");
    let library = body["library_id"]
        .as_str()
        .map(str::to_owned)
        .or_else(|| store.libraries().into_iter().next())
        .unwrap_or_default();
    let links: Vec<Value> = body["items"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|link| {
            let paper = store.get("item", &text(link, "item_id"))?;
            Some(json!({"item_id": paper["id"], "title": paper["title"], "page": link["page"]}))
        })
        .collect();
    let at = now();
    let note = json!({
        "id": id,
        "library_id": library,
        "title": title_of(&words),
        "excerpt": excerpt_of(&words),
        "items": links,
        "collection_ids": body["collection_id"].as_str().map_or(json!([]), |c| json!([c])),
        "created_at": at,
        "changed_at": at,
        "changed_by": my_name(store),
        "change": 0,
        "deleted_at": null,
        "text": words,
        "etag": "",
    });
    store.put("note", &note)?;
    store.enqueue(&Queued {
        method: "POST".into(),
        path: "/api/notes".into(),
        body: Some(body.to_string()),
        key: Some(format!("new note {id}")),
        what: format!("A note: “{}”", title_of(&words)),
        ..Queued::default()
    })?;
    Ok(json_response(201, &note))
}

fn change_note(store: &Store, id: &str, body: Value) -> rusqlite::Result<Response<Vec<u8>>> {
    let Some(mut note) = store.get("note", id) else {
        return Ok(not_found("note"));
    };
    let words = text(&body, "text");
    note["text"] = json!(words);
    note["title"] = json!(title_of(&words));
    note["excerpt"] = json!(excerpt_of(&words));
    note["changed_at"] = json!(now());
    note["changed_by"] = json!(my_name(store));
    store.put("note", &note)?;
    let what = format!("Your text of the note “{}”", title_of(&words));
    let new = format!("new note {id}");
    if let Some(mut making) = store.queued_by_key(&new) {
        let mut sent: Value = making
            .body
            .as_deref()
            .and_then(|body| serde_json::from_str(body).ok())
            .unwrap_or_else(|| json!({}));
        sent["text"] = json!(words);
        making.body = Some(sent.to_string());
        making.what = what;
        store.enqueue(&making)?;
    } else {
        // The version the text started from offline, kept until sent.
        let etag = text(&note, "etag");
        store.enqueue(&Queued {
            method: "PATCH".into(),
            path: format!("/api/notes/{id}"),
            body: Some(json!({"text": words}).to_string()),
            if_match: Some(format!("\"{etag}\"")),
            key: Some(format!("note {id}")),
            what,
            ..Queued::default()
        })?;
    }
    let mut response = json_response(200, &note);
    response.headers_mut().insert(
        "ETag",
        format!(
            "\"offline-{}\"",
            note["changed_at"].as_str().unwrap_or_default()
        )
        .parse()
        .expect("a header"),
    );
    Ok(response)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::offline::store::Changes;

    fn store() -> Store {
        let mut store = Store::in_memory().unwrap();
        let changes: Changes = serde_json::from_value(json!({
            "change": 5, "libraries": ["own"], "removed": [],
            "items": [{"id": "p1", "library_id": "own", "title": "On light", "files": [{"id": "f1"}]}],
            "notes": [{"id": "n1", "library_id": "own", "title": "Seminar", "text": "# Seminar", "etag": "123"}],
            "tags": [], "collections": [],
            "annotations": [{"id": "a1", "item_id": "p1", "file_id": "f1", "page_index": 2,
                             "comment": "Key", "change": 4}],
            "views": []
        }))
        .unwrap();
        store.apply(&changes, false).unwrap();
        store
    }

    fn sent(store: &Store) -> Vec<(String, String, Option<Value>, Option<String>)> {
        store
            .queued()
            .into_iter()
            .map(|change| {
                (
                    change.method,
                    change.path,
                    change
                        .body
                        .and_then(|body| serde_json::from_str(&body).ok()),
                    change.if_match,
                )
            })
            .collect()
    }

    #[test]
    fn new_ids_are_uuid7s() {
        let id = new_id();
        assert_eq!(id.len(), 36);
        assert_eq!(&id[14..15], "7");
        assert!(matches!(&id[19..20], "8" | "9" | "a" | "b"));
        assert_ne!(new_id(), id);
        assert!(now().ends_with('Z') && now().starts_with("20"));
    }

    #[test]
    fn annotations_made_changed_removed() {
        let store = store();
        let made = change(
            &store,
            "POST",
            "/api/files/f1/annotations",
            br##"{"kind": "highlight", "page_index": 0, "position": {"rects": [[1, 2, 3, 4]]}, "color": "#FFD400"}"##,
        );
        assert_eq!(made.status(), 201);
        let made: Value = serde_json::from_slice(made.body()).unwrap();
        let id = text(&made, "id");
        assert_eq!(
            (made["color"].clone(), made["mine"].clone()),
            (json!("#ffd400"), json!(true))
        );
        assert_eq!(store.get("annotation", &id).unwrap()["item_id"], "p1");
        // Changed before it was sent: one create, with the change.
        let changed = change(
            &store,
            "PATCH",
            &format!("/api/annotations/{id}"),
            br#"{"comment": "Later"}"#,
        );
        assert_eq!(changed.status(), 200);
        let queued = sent(&store);
        assert_eq!(queued.len(), 1);
        assert_eq!(queued[0].2.as_ref().unwrap()["comment"], "Later");
        assert_eq!(queued[0].2.as_ref().unwrap()["id"], json!(id));
        // Removed before it was sent: nothing to send.
        assert_eq!(
            change(&store, "DELETE", &format!("/api/annotations/{id}"), b"").status(),
            204
        );
        assert!(sent(&store).is_empty());

        // One from the server: changed twice, sent once, from its version.
        change(
            &store,
            "PATCH",
            "/api/annotations/a1",
            br#"{"comment": "One"}"#,
        );
        change(
            &store,
            "PATCH",
            "/api/annotations/a1",
            br##"{"color": "#5FB236"}"##,
        );
        assert_eq!(
            sent(&store),
            [(
                "PATCH".into(),
                "/api/annotations/a1".into(),
                Some(json!({"comment": "One", "color": "#5FB236"})),
                Some("\"4\"".into())
            )]
        );
        change(&store, "DELETE", "/api/annotations/a1", b"");
        assert_eq!(sent(&store)[0].0, "DELETE");
        assert_eq!(sent(&store).len(), 1);
        assert!(store.get("annotation", "a1").is_none());
        assert_eq!(
            change(&store, "PATCH", "/api/annotations/a1", b"{}").status(),
            404
        );
        assert_eq!(
            change(&store, "POST", "/api/files/nope/annotations", b"{}").status(),
            404
        );
    }

    #[test]
    fn reading_and_notes() {
        let store = store();
        let place = br#"{"file_id": "f1", "page": 3, "top": 10.0}"#;
        assert_eq!(
            change(&store, "PUT", "/api/items/p1/reading", place).status(),
            204
        );
        change(
            &store,
            "PUT",
            "/api/items/p1/reading",
            br#"{"file_id": "f1", "page": 4, "top": 0.0}"#,
        );
        assert_eq!(store.get("view", "p1").unwrap()["reading"]["page"], 4);
        assert_eq!(sent(&store).len(), 1);

        let saved = change(
            &store,
            "PATCH",
            "/api/notes/n1",
            b"{\"text\": \"# Seminar, revised\\n\\nMore\"}",
        );
        assert_eq!(saved.status(), 200);
        let note = store.get("note", "n1").unwrap();
        assert_eq!(
            (text(&note, "title"), text(&note, "excerpt")),
            ("Seminar, revised".into(), "More".into())
        );
        let queued = sent(&store);
        assert_eq!(queued[1].3.as_deref(), Some("\"123\""));

        let made = change(
            &store,
            "POST",
            "/api/notes",
            br##"{"text": "# New", "items": [{"item_id": "p1"}]}"##,
        );
        let made: Value = serde_json::from_slice(made.body()).unwrap();
        assert_eq!(made["items"][0]["title"], "On light");
        assert_eq!(made["library_id"], "own");
        change(
            &store,
            "PATCH",
            &format!("/api/notes/{}", text(&made, "id")),
            br##"{"text": "# New, longer"}"##,
        );
        assert_eq!(sent(&store).len(), 3);
        assert_eq!(sent(&store)[2].2.as_ref().unwrap()["text"], "# New, longer");

        assert_eq!(change(&store, "POST", "/api/tags", b"{}").status(), 503);
    }

    #[test]
    fn titles_as_the_server_makes_them() {
        assert_eq!(title_of("\n## *Seminar* notes\n\ntext"), "Seminar notes");
        assert_eq!(title_of(""), "");
        assert_eq!(
            excerpt_of("# Title\n\nFirst line\nsecond"),
            "First line second"
        );
    }
}
