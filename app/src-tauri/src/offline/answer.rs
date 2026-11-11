//! The website's calls answered from the copy, as the server would answer
//! them (`server/src/paperus/api`): lists of papers and notes, a paper's
//! page (kept whole for the papers opened last, else from its details),
//! its files and annotations, keyword search in the details and notes, and
//! the account as last seen. Changes go to `write`. What cannot be done
//! offline says so (503).

use std::{collections::HashSet, fs, path::Path};

use serde_json::{Value, json};
use tauri::http::{Method, Request, Response};

use super::Store;

/// The annotation colours offered (`server/src/paperus/annotations.py`).
const COLORS: [&str; 8] = [
    "#ffd400", "#ff6666", "#5fb236", "#2ea8e5", "#a28ae5", "#e56eee", "#f19837", "#aaaaaa",
];

/// The query's values of ``name``.
struct Query(Vec<(String, String)>);

impl Query {
    fn parse(query: Option<&str>) -> Query {
        Query(
            url::form_urlencoded::parse(query.unwrap_or_default().as_bytes())
                .into_owned()
                .collect(),
        )
    }

    fn all(&self, name: &str) -> Vec<&str> {
        self.0
            .iter()
            .filter(|(key, _)| key == name)
            .map(|(_, value)| value.as_str())
            .collect()
    }

    fn one(&self, name: &str) -> Option<&str> {
        self.all(name).first().copied()
    }

    fn flag(&self, name: &str) -> bool {
        self.one(name) == Some("true")
    }

    fn number(&self, name: &str, default: usize) -> usize {
        self.one(name)
            .and_then(|value| value.parse().ok())
            .unwrap_or(default)
    }
}

fn json_response(status: u16, body: &Value) -> Response<Vec<u8>> {
    Response::builder()
        .status(status)
        .header("Content-Type", "application/json")
        .body(body.to_string().into_bytes())
        .expect("a response")
}

fn list_response(records: Vec<Value>, total: usize) -> Response<Vec<u8>> {
    Response::builder()
        .header("Content-Type", "application/json")
        .header("X-Total-Count", total.to_string())
        .body(Value::Array(records).to_string().into_bytes())
        .expect("a response")
}

/// What cannot be done offline.
pub fn unavailable() -> Response<Vec<u8>> {
    json_response(
        503,
        &json!({"detail": "Not available offline: it needs the library's server."}),
    )
}

fn kept(store: &Store, path: &str) -> Option<Response<Vec<u8>>> {
    let (_, media_type, body) = store.answer(path)?;
    Some(
        Response::builder()
            .header("Content-Type", media_type)
            .body(body)
            .expect("a response"),
    )
}

/// The answer to the website's call ``request``.
pub fn answer(store: &Store, folder: &Path, request: &Request<Vec<u8>>) -> Response<Vec<u8>> {
    let path = request.uri().path();
    let query = Query::parse(request.uri().query());
    let parts: Vec<&str> = path.trim_matches('/').split('/').collect();
    if request.method() != Method::GET {
        return super::write::change(store, request.method().as_str(), path, request.body());
    }
    match parts.as_slice() {
        ["api", "items"] => items(store, &query),
        ["api", "items", id] => kept(store, path).unwrap_or_else(|| paper_page(store, id)),
        ["api", "items", id, "reading"] => json_response(
            200,
            &store
                .get("view", id)
                .map_or(Value::Null, |view| view["reading"].clone()),
        ),
        ["api", "items", _, "references" | "cited-by"] => {
            kept(store, path).unwrap_or_else(|| json_response(200, &json!([])))
        }
        ["api", "notes"] => notes(store, &query),
        ["api", "notes", id] => store
            .get("note", id)
            .map_or_else(unavailable, |note| json_response(200, &note)),
        ["api", "files", id, "content"] => content(store, folder, id),
        ["api", "files", id, "annotations"] => annotations(store, path, id),
        ["api", "search"] => search(store, &query),
        _ => kept(store, path).unwrap_or_else(unavailable),
    }
}

fn text(record: &Value, field: &str) -> String {
    record[field].as_str().unwrap_or_default().to_owned()
}

/// The collection and those inside it (``nested``).
fn collections_in(store: &Store, id: &str, nested: bool) -> HashSet<String> {
    let mut found = HashSet::from([id.to_owned()]);
    if nested {
        let all = store.all("collection");
        loop {
            let more: Vec<String> = all
                .iter()
                .filter(|c| {
                    found.contains(&text(c, "parent_id")) && !found.contains(&text(c, "id"))
                })
                .map(|c| text(c, "id"))
                .collect();
            if more.is_empty() {
                break;
            }
            found.extend(more);
        }
    }
    found
}

/// Whether one of the paper's authors is this one ("Family, Given": the
/// family name, and the given name's first letter if one is given).
fn by_author(item: &Value, name: &str) -> bool {
    let (family, given) = name.split_once(',').unwrap_or((name, ""));
    let (family, initial) = (
        family.trim().to_lowercase(),
        given
            .trim()
            .chars()
            .next()
            .map(|c| c.to_lowercase().to_string()),
    );
    item["authors"]
        .as_array()
        .into_iter()
        .flatten()
        .any(|author| {
            let author = author.as_str().unwrap_or_default().to_lowercase();
            let (their_family, their_given) = author.split_once(',').unwrap_or((&author, ""));
            their_family.trim() == family
                && initial
                    .as_ref()
                    .is_none_or(|initial| their_given.trim().starts_with(initial.as_str()))
        })
}

/// `GET /api/items`: newest first, filtered as the server does.
fn items(store: &Store, query: &Query) -> Response<Vec<u8>> {
    let favourites: HashSet<String> = store.favourites().into_iter().collect();
    let views: Vec<Value> = store.all("view");
    let viewed_at = |id: &str| {
        views
            .iter()
            .find(|view| text(view, "item_id") == id)
            .and_then(|view| view["viewed_at"].as_str().map(str::to_owned))
    };
    let ids = query.all("id");
    let tags_all = query.all("tag");
    let tags_any = query.all("tag_any");
    let tags_none = query.all("tag_none");
    let trashed = query.flag("trashed");
    let archived = query.flag("archived");
    let collection = query
        .one("collection")
        .map(|id| collections_in(store, id, query.one("nested") != Some("false")));
    let smart = query
        .one("collection")
        .and_then(|id| store.get("collection", id))
        .is_some_and(|c| !c["rules"].is_null());
    let words: Vec<String> = query
        .one("title")
        .unwrap_or_default()
        .split_whitespace()
        .map(str::to_lowercase)
        .collect();
    let sort = query.one("sort").unwrap_or("added");
    let mut found: Vec<Value> = store
        .all("item")
        .into_iter()
        .map(|mut item| {
            let id = text(&item, "id");
            item["favourite"] = json!(favourites.contains(&id));
            if sort != "added" {
                item["viewed_at"] = json!(viewed_at(&id));
            }
            item
        })
        .filter(|item| {
            let id = text(item, "id");
            let tags: HashSet<String> = item["tags"]
                .as_array()
                .into_iter()
                .flatten()
                .map(|tag| text(tag, "id"))
                .collect();
            let in_collections: HashSet<String> = item["collection_ids"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|id| id.as_str().map(str::to_owned))
                .collect();
            let title = text(item, "title").to_lowercase();
            // The archive only when asked for (or by id, or in the trash).
            let in_archive = !item["archived_at"].is_null();
            let shown_archive = if archived {
                in_archive
            } else {
                trashed || !ids.is_empty() || !in_archive
            };
            item["deleted_at"].is_null() != trashed
                && shown_archive
                && (ids.is_empty() || ids.contains(&id.as_str()))
                && tags_all.iter().all(|tag| tags.contains(*tag))
                && (tags_any.is_empty() || tags_any.iter().any(|tag| tags.contains(*tag)))
                && !tags_none.iter().any(|tag| tags.contains(*tag))
                && query
                    .one("library")
                    .is_none_or(|library| text(item, "library_id") == library)
                && (!query.flag("favourite") || favourites.contains(&id))
                && query.one("author").is_none_or(|name| by_author(item, name))
                && words.iter().all(|word| title.contains(word))
                && collection
                    .as_ref()
                    .is_none_or(|wanted| !smart && !wanted.is_disjoint(&in_collections))
                // Papers whose details could not be found: the server knows.
                && !query.flag("unsorted")
                && (sort != "opened" || viewed_at(&id).is_some())
        })
        .collect();
    let limit = query.number("limit", 50);
    let total = found.len();
    if sort == "added" {
        found.sort_by_key(|item| std::cmp::Reverse(text(item, "id")));
        if let Some(before) = query.one("before") {
            found.retain(|item| text(item, "id").as_str() < before);
        }
        found.truncate(limit);
    } else {
        let activity = |item: &Value| {
            let changed = text(item, "changed_at");
            let viewed = item["viewed_at"].as_str().unwrap_or_default().to_owned();
            if sort == "recent" {
                changed.max(viewed)
            } else {
                viewed
            }
        };
        found.sort_by_key(|item| std::cmp::Reverse((activity(item), text(item, "id"))));
        found = found
            .into_iter()
            .skip(query.number("offset", 0))
            .take(limit)
            .collect();
    }
    list_response(found, total)
}

/// A paper's page from its details, for one not kept whole: what the
/// website needs, without its versions' details.
fn paper_page(store: &Store, id: &str) -> Response<Vec<u8>> {
    let Some(mut item) = store.get("item", id) else {
        return json_response(404, &json!({"detail": "item not found"}));
    };
    item["favourite"] = json!(store.favourites().iter().any(|starred| starred == id));
    for (field, empty) in [
        ("added_by", Value::Null),
        ("csl", json!({})),
        ("abstract", Value::Null),
        ("overrides", json!({})),
        ("preferred_version_id", Value::Null),
        ("versions", json!([])),
    ] {
        item[field] = empty;
    }
    json_response(200, &item)
}

/// `GET /api/notes`: last changed first.
fn notes(store: &Store, query: &Query) -> Response<Vec<u8>> {
    let trashed = query.flag("trashed");
    let collection = query
        .one("collection")
        .map(|id| collections_in(store, id, query.one("nested") != Some("false")));
    let mut found: Vec<Value> = store
        .all("note")
        .into_iter()
        .filter(|note| {
            note["deleted_at"].is_null() != trashed
                && query.one("item").is_none_or(|item| {
                    note["items"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .any(|link| text(link, "item_id") == item)
                })
                && collection.as_ref().is_none_or(|wanted| {
                    note["collection_ids"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .any(|id| id.as_str().is_some_and(|id| wanted.contains(id)))
                })
        })
        .collect();
    found.sort_by(|a, b| {
        (text(b, "changed_at"), text(b, "id")).cmp(&(text(a, "changed_at"), text(a, "id")))
    });
    let total = found.len();
    let found = found
        .into_iter()
        .skip(query.number("offset", 0))
        .take(query.number("limit", 50))
        .map(|mut note| {
            if let Some(fields) = note.as_object_mut() {
                fields.remove("text");
            }
            note
        })
        .collect();
    list_response(found, total)
}

/// A file kept with its paper.
fn content(store: &Store, folder: &Path, id: &str) -> Response<Vec<u8>> {
    let Ok(bytes) = fs::read(folder.join("files").join(id)) else {
        return json_response(
            503,
            &json!({"detail": "This file was not kept for offline use."}),
        );
    };
    let media_type = store
        .all("item")
        .iter()
        .flat_map(|item| item["files"].as_array().cloned().unwrap_or_default())
        .find(|file| text(file, "id") == id)
        .map_or_else(
            || "application/pdf".to_owned(),
            |file| text(&file, "media_type"),
        );
    Response::builder()
        .header("Content-Type", media_type)
        .body(bytes)
        .expect("a response")
}

/// Top to bottom on each page (`annotations.reading_order`).
fn reading_order(annotation: &Value) -> (i64, i64, i64) {
    let position = &annotation["position"];
    let numbers = |field: &str, pick: fn(&[Value]) -> Vec<f64>| -> Vec<f64> {
        position[field]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(Value::as_array)
            .flat_map(|values| pick(values))
            .collect()
    };
    let ys = [
        numbers("rects", |r| {
            vec![
                r.get(1)
                    .and_then(Value::as_f64)
                    .unwrap_or(0.0)
                    .max(r.get(3).and_then(Value::as_f64).unwrap_or(0.0)),
            ]
        }),
        numbers("paths", |p| {
            p.iter()
                .skip(1)
                .step_by(2)
                .filter_map(Value::as_f64)
                .collect()
        }),
    ]
    .concat();
    let xs = [
        numbers("rects", |r| {
            vec![
                r.first()
                    .and_then(Value::as_f64)
                    .unwrap_or(0.0)
                    .min(r.get(2).and_then(Value::as_f64).unwrap_or(0.0)),
            ]
        }),
        numbers("paths", |p| {
            p.iter().step_by(2).filter_map(Value::as_f64).collect()
        }),
    ]
    .concat();
    let top = ys.iter().copied().fold(None, |most: Option<f64>, y| {
        Some(most.map_or(y, |m| m.max(y)))
    });
    let left = xs.iter().copied().fold(None, |least: Option<f64>, x| {
        Some(least.map_or(x, |l| l.min(x)))
    });
    (
        annotation["page_index"].as_i64().unwrap_or(0),
        -(top.unwrap_or(0.0) * 1000.0) as i64,
        (left.unwrap_or(0.0) * 1000.0) as i64,
    )
}

/// A file's annotations as they are now, with what was kept of the rest
/// of its answer (the PDF's own marks to leave out, sharing).
fn annotations(store: &Store, path: &str, id: &str) -> Response<Vec<u8>> {
    let mut answer = store
        .answer(path)
        .and_then(|(_, _, body)| serde_json::from_slice::<Value>(&body).ok())
        .unwrap_or_else(
            || json!({"hidden_marks": [], "shared": false, "can_share": false, "colors": COLORS}),
        );
    let mut found: Vec<Value> = store
        .all("annotation")
        .into_iter()
        .filter(|annotation| text(annotation, "file_id") == id)
        .map(|mut annotation| {
            if let Some(fields) = annotation.as_object_mut() {
                fields.remove("item_id");
            }
            annotation
        })
        .collect();
    found.sort_by_key(reading_order);
    answer["annotations"] = Value::Array(found);
    json_response(200, &answer)
}

fn escaped(text: &str) -> String {
    text.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

/// `GET /api/search`: the words in papers' details (title, authors) and in
/// notes; the full text and search by meaning need the server.
fn search(store: &Store, query: &Query) -> Response<Vec<u8>> {
    let words: Vec<String> = query
        .one("q")
        .unwrap_or_default()
        .split_whitespace()
        .map(|word| word.trim_matches('"').to_lowercase())
        .filter(|word| !word.is_empty() && !word.starts_with('-'))
        .collect();
    let has_all = |haystack: &str| {
        let haystack = haystack.to_lowercase();
        !words.is_empty() && words.iter().all(|word| haystack.contains(word))
    };
    let within = query.one("item");
    let mut found: Vec<Value> = Vec::new();
    for item in store.all("item") {
        let authors: Vec<String> = item["authors"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|a| a.as_str().map(str::to_owned))
            .collect();
        let id = text(&item, "id");
        let shown = item["deleted_at"].is_null()
            && (query.flag("archived") || item["archived_at"].is_null())
            && within.is_none_or(|within| within == id);
        if shown && has_all(&format!("{} {}", text(&item, "title"), authors.join(" "))) {
            found.push(json!({
                "passage_id": format!("{id}#details"),
                "kind": "details",
                "item_id": id,
                "item_title": text(&item, "title"),
                "item_authors": authors,
                "item_year": item["year"],
                "version_id": null,
                "file_id": null,
                "position": 0,
                "page": null,
                "snippet": escaped(&text(&item, "title")),
                "score": 1.0,
                "matched": ["keyword"],
                "in_references": false,
            }));
        }
    }
    if within.is_none() {
        for note in store.all("note") {
            if note["deleted_at"].is_null() && has_all(&text(&note, "text")) {
                found.push(json!({
                    "passage_id": text(&note, "id"),
                    "kind": "note",
                    "item_id": null,
                    "item_title": text(&note, "title"),
                    "version_id": null,
                    "file_id": null,
                    "note_id": text(&note, "id"),
                    "position": 0,
                    "page": null,
                    "snippet": escaped(&text(&note, "excerpt")),
                    "score": 1.0,
                    "matched": ["keyword"],
                    "in_references": false,
                }));
            }
        }
    }
    found.truncate(query.number("limit", 20));
    let mut response = json_response(200, &Value::Array(found));
    response
        .headers_mut()
        .insert("X-Search-Mode", "keyword".parse().expect("a header"));
    response
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::offline::store::Changes;

    fn store() -> Store {
        let store = Store::in_memory().unwrap();
        let changes: Changes = serde_json::from_value(json!({
            "change": 5, "libraries": ["own"], "removed": [],
            "items": [
                {"id": "01a", "library_id": "own", "title": "On light", "authors": ["Einstein, Albert"],
                 "tags": [{"id": "t1"}], "collection_ids": ["c2"], "deleted_at": null, "archived_at": null,
                 "changed_at": "2026-11-01", "files": [{"id": "f1", "media_type": "application/pdf"}]},
                {"id": "01b", "library_id": "own", "title": "Species", "authors": ["Darwin, Charles"],
                 "tags": [], "collection_ids": [], "deleted_at": null, "archived_at": null,
                 "changed_at": "2026-11-02", "files": []},
                {"id": "01c", "library_id": "own", "title": "Gone", "authors": [],
                 "tags": [], "collection_ids": [], "deleted_at": "2026-11-03", "archived_at": null,
                 "changed_at": "2026-11-03", "files": []}
            ],
            "notes": [{"id": "n1", "library_id": "own", "title": "Seminar", "text": "# Seminar\n\nlight quanta",
                       "excerpt": "light quanta", "items": [{"item_id": "01a"}], "collection_ids": [],
                       "deleted_at": null, "changed_at": "2026-11-04"}],
            "tags": [],
            "collections": [{"id": "c1", "library_id": "own", "parent_id": null, "rules": null},
                            {"id": "c2", "library_id": "own", "parent_id": "c1", "rules": null}],
            "annotations": [
                {"id": "a2", "item_id": "01a", "file_id": "f1", "page_index": 0, "position": {"rects": [[10, 100, 20, 110]]}},
                {"id": "a1", "item_id": "01a", "file_id": "f1", "page_index": 0, "position": {"rects": [[10, 700, 20, 710]]}}
            ],
            "views": [{"item_id": "01b", "viewed_at": "2026-11-05", "reading": {"page": 2}}],
            "favourites": ["01b"]
        }))
        .unwrap();
        let mut store = store;
        store.apply(&changes, false).unwrap();
        store
    }

    fn get(store: &Store, address: &str) -> (u16, Value) {
        let request = Request::builder()
            .uri(format!("paperus-offline://localhost{address}"))
            .body(Vec::new())
            .unwrap();
        let response = answer(store, Path::new("/nowhere"), &request);
        let body = serde_json::from_slice(response.body()).unwrap_or(Value::Null);
        (response.status().as_u16(), body)
    }

    fn titles(body: &Value) -> Vec<String> {
        body.as_array()
            .into_iter()
            .flatten()
            .map(|item| text(item, "title"))
            .collect()
    }

    #[test]
    fn lists_as_the_server_does() {
        let store = store();
        assert_eq!(
            titles(&get(&store, "/api/items?limit=50").1),
            ["Species", "On light"]
        );
        assert_eq!(titles(&get(&store, "/api/items?limit=1").1), ["Species"]);
        assert_eq!(
            titles(&get(&store, "/api/items?before=01b").1),
            ["On light"]
        );
        assert_eq!(titles(&get(&store, "/api/items?trashed=true").1), ["Gone"]);
        assert_eq!(titles(&get(&store, "/api/items?tag=t1").1), ["On light"]);
        assert_eq!(
            titles(&get(&store, "/api/items?favourite=true").1),
            ["Species"]
        );
        assert_eq!(
            titles(&get(&store, "/api/items?author=Darwin%2C%20C").1),
            ["Species"]
        );
        assert_eq!(
            titles(&get(&store, "/api/items?author=Darwin%2C%20E").1),
            Vec::<String>::new()
        );
        // A collection, with those inside it unless not nested.
        assert_eq!(
            titles(&get(&store, "/api/items?collection=c1").1),
            ["On light"]
        );
        assert!(titles(&get(&store, "/api/items?collection=c1&nested=false").1).is_empty());
        assert_eq!(
            titles(&get(&store, "/api/items?sort=opened").1),
            ["Species"]
        );
        assert_eq!(
            titles(&get(&store, "/api/items?title=LIGHT").1),
            ["On light"]
        );
    }

    #[test]
    fn a_papers_page_and_its_annotations() {
        let store = store();
        let (status, page) = get(&store, "/api/items/01b");
        assert_eq!(
            (status, page["favourite"].clone(), page["versions"].clone()),
            (200, json!(true), json!([]))
        );
        assert_eq!(get(&store, "/api/items/01b/reading").1, json!({"page": 2}));
        assert_eq!(get(&store, "/api/items/01a/reading").1, Value::Null);
        let marks = get(&store, "/api/files/f1/annotations").1;
        let order: Vec<String> = marks["annotations"]
            .as_array()
            .unwrap()
            .iter()
            .map(|a| text(a, "id"))
            .collect();
        assert_eq!(order, ["a1", "a2"]);
        assert_eq!(marks["colors"][0], "#ffd400");
        assert_eq!(get(&store, "/api/files/f1/content").0, 503);
        assert_eq!(get(&store, "/api/items/missing").0, 404);
    }

    #[test]
    fn notes_search_and_the_rest() {
        let store = store();
        let (_, notes) = get(&store, "/api/notes?item=01a");
        assert_eq!(titles(&notes), ["Seminar"]);
        assert!(notes[0].get("text").is_none());
        assert_eq!(
            get(&store, "/api/notes/n1").1["text"],
            "# Seminar\n\nlight quanta"
        );
        let found = get(&store, "/api/search?q=light").1;
        let kinds: Vec<String> = found
            .as_array()
            .unwrap()
            .iter()
            .map(|p| text(p, "kind"))
            .collect();
        assert_eq!(kinds, ["details", "note"]);
        assert_eq!(
            get(&store, "/api/search?q=einstein").1[0]["item_title"],
            "On light"
        );
        assert_eq!(get(&store, "/api/duplicates").0, 503);
        let post = Request::builder()
            .method("POST")
            .uri("paperus-offline://localhost/api/tags")
            .body(Vec::new())
            .unwrap();
        assert_eq!(answer(&store, Path::new("/nowhere"), &post).status(), 503);
    }
}
