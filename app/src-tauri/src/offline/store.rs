//! The copy of one library (see the module): its records as `/api/changes`
//! gives them, and answers kept whole (a paper's page, the person's
//! account), in one SQLite file.

use rusqlite::{Connection, OptionalExtension, params};
use serde::Deserialize;
use serde_json::Value;

use crate::libraries;

/// One answer of `/api/changes`.
#[derive(Deserialize)]
pub struct Changes {
    pub change: i64,
    pub libraries: Vec<String>,
    removed: Vec<Removed>,
    items: Vec<Value>,
    notes: Vec<Value>,
    tags: Vec<Value>,
    collections: Vec<Value>,
    annotations: Vec<Value>,
    views: Vec<Value>,
    /// All the papers the person starred (servers before 0.0.22: none).
    #[serde(default)]
    favourites: Vec<String>,
}

#[derive(Deserialize)]
struct Removed {
    id: String,
    kind: String,
}

/// The copy of one library.
pub struct Store {
    db: Connection,
}

impl Store {
    pub fn open(path: &std::path::Path) -> rusqlite::Result<Store> {
        Store::new(Connection::open(path)?)
    }

    #[cfg(test)]
    pub fn in_memory() -> rusqlite::Result<Store> {
        Store::new(Connection::open_in_memory()?)
    }

    fn new(db: Connection) -> rusqlite::Result<Store> {
        db.execute_batch(
            "PRAGMA journal_mode = WAL;
             CREATE TABLE IF NOT EXISTS records (
                 kind TEXT NOT NULL,
                 id TEXT NOT NULL,
                 library_id TEXT,
                 item_id TEXT,
                 json TEXT NOT NULL,
                 PRIMARY KEY (kind, id)
             );
             CREATE INDEX IF NOT EXISTS records_item ON records (item_id);
             CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS answers (
                 path TEXT PRIMARY KEY,
                 change INTEGER NOT NULL,
                 type TEXT NOT NULL,
                 body BLOB NOT NULL
             );",
        )?;
        Ok(Store { db })
    }

    /// The change number to ask from (0: nothing kept yet).
    pub fn since(&self) -> i64 {
        self.state("since")
            .and_then(|value| value.parse().ok())
            .unwrap_or(0)
    }

    /// The papers the person starred, as of the last sync.
    pub fn favourites(&self) -> Vec<String> {
        self.state("favourites")
            .and_then(|value| serde_json::from_str(&value).ok())
            .unwrap_or_default()
    }

    /// The libraries the person read at the last sync.
    pub fn libraries(&self) -> Vec<String> {
        self.state("libraries")
            .and_then(|value| serde_json::from_str(&value).ok())
            .unwrap_or_default()
    }

    fn state(&self, key: &str) -> Option<String> {
        self.db
            .query_row("SELECT value FROM state WHERE key = ?1", [key], |row| {
                row.get(0)
            })
            .optional()
            .ok()
            .flatten()
    }

    /// A record kept (``kind``: item, note, tag, collection, annotation,
    /// view; a view's id is its paper's).
    pub fn get(&self, kind: &str, id: &str) -> Option<Value> {
        let json: String = self
            .db
            .query_row(
                "SELECT json FROM records WHERE kind = ?1 AND id = ?2",
                [kind, id],
                |row| row.get(0),
            )
            .optional()
            .ok()??;
        serde_json::from_str(&json).ok()
    }

    /// All records of a kind.
    pub fn all(&self, kind: &str) -> Vec<Value> {
        let Ok(mut query) = self
            .db
            .prepare("SELECT json FROM records WHERE kind = ?1 ORDER BY id")
        else {
            return Vec::new();
        };
        query
            .query_map([kind], |row| row.get::<_, String>(0))
            .map(|rows| {
                rows.filter_map(|json| serde_json::from_str(&json.ok()?).ok())
                    .collect()
            })
            .unwrap_or_default()
    }

    /// Forget everything (a sync from 0 follows).
    pub fn clear(&mut self) -> rusqlite::Result<()> {
        self.db
            .execute_batch("DELETE FROM records; DELETE FROM state; DELETE FROM answers;")
    }

    /// Keep the server's answer to ``path`` (as of change number
    /// ``change``) to give it offline.
    pub fn keep_answer(
        &self,
        path: &str,
        change: i64,
        media_type: &str,
        body: &[u8],
    ) -> rusqlite::Result<()> {
        self.db.execute(
            "INSERT OR REPLACE INTO answers (path, change, type, body) VALUES (?1, ?2, ?3, ?4)",
            params![path, change, media_type, body],
        )?;
        Ok(())
    }

    /// An answer kept: its change number, media type and body.
    pub fn answer(&self, path: &str) -> Option<(i64, String, Vec<u8>)> {
        self.db
            .query_row(
                "SELECT change, type, body FROM answers WHERE path = ?1",
                [path],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .optional()
            .ok()?
    }

    /// Answers kept whose path starts with ``prefix``.
    pub fn answer_paths(&self, prefix: &str) -> Vec<String> {
        let Ok(mut query) = self
            .db
            .prepare("SELECT path FROM answers WHERE substr(path, 1, length(?1)) = ?1")
        else {
            return Vec::new();
        };
        query
            .query_map([prefix], |row| row.get(0))
            .map(|rows| rows.filter_map(Result::ok).collect())
            .unwrap_or_default()
    }

    /// Let an answer go.
    pub fn drop_answer(&self, path: &str) -> rusqlite::Result<()> {
        self.db
            .execute("DELETE FROM answers WHERE path = ?1", [path])?;
        Ok(())
    }

    /// Take in an answer of `/api/changes`: removals first, then the
    /// records as they are now. ``partial``: for some libraries only
    /// (`library=`), which neither moves the change number nor says what is
    /// out of reach.
    pub fn apply(&mut self, changes: &Changes, partial: bool) -> rusqlite::Result<()> {
        let db = self.db.transaction()?;
        if !partial {
            // Out of reach (a group left): what belonged to other libraries.
            let readable = serde_json::to_string(&changes.libraries).unwrap_or_default();
            db.execute(
                "DELETE FROM records WHERE library_id IS NOT NULL
                 AND library_id NOT IN (SELECT value FROM json_each(?1))",
                [&readable],
            )?;
        }
        for removed in &changes.removed {
            match removed.kind.as_str() {
                // A file: from its paper's list, with its annotations.
                "file" => {
                    db.execute(
                        "DELETE FROM records WHERE kind = 'annotation'
                         AND json_extract(json, '$.file_id') = ?1",
                        [&removed.id],
                    )?;
                    db.execute(
                        "UPDATE records SET json = json_set(json, '$.files', json((
                             SELECT json_group_array(json(value))
                             FROM json_each(records.json, '$.files')
                             WHERE json_extract(value, '$.id') != ?1)))
                         WHERE kind = 'item' AND EXISTS (
                             SELECT 1 FROM json_each(records.json, '$.files')
                             WHERE json_extract(value, '$.id') = ?1)",
                        [&removed.id],
                    )?;
                }
                kind => {
                    db.execute(
                        "DELETE FROM records WHERE kind = ?1 AND id = ?2",
                        [kind, removed.id.as_str()],
                    )?;
                }
            }
        }
        {
            let mut put = db.prepare(
                "INSERT INTO records (kind, id, library_id, item_id, json)
                 VALUES (?1, ?2, ?3, ?4, ?5)
                 ON CONFLICT (kind, id) DO UPDATE SET
                     library_id = excluded.library_id,
                     item_id = excluded.item_id,
                     json = excluded.json",
            )?;
            let text = |record: &Value, field: &str| record[field].as_str().map(str::to_owned);
            for (kind, records) in [
                ("item", &changes.items),
                ("note", &changes.notes),
                ("tag", &changes.tags),
                ("collection", &changes.collections),
            ] {
                for record in records {
                    put.execute(params![
                        kind,
                        text(record, "id"),
                        text(record, "library_id"),
                        None::<String>,
                        record.to_string()
                    ])?;
                }
            }
            for record in &changes.annotations {
                put.execute(params![
                    "annotation",
                    text(record, "id"),
                    None::<String>,
                    text(record, "item_id"),
                    record.to_string()
                ])?;
            }
            for record in &changes.views {
                put.execute(params![
                    "view",
                    text(record, "item_id"),
                    None::<String>,
                    text(record, "item_id"),
                    record.to_string()
                ])?;
            }
        }
        // What went with a paper no longer kept.
        db.execute(
            "DELETE FROM records WHERE item_id IS NOT NULL AND item_id NOT IN (
                 SELECT id FROM records WHERE kind = 'item')",
            [],
        )?;
        if !partial {
            let readable = serde_json::to_string(&changes.libraries).unwrap_or_default();
            let starred = serde_json::to_string(&changes.favourites).unwrap_or_default();
            db.execute(
                "INSERT OR REPLACE INTO state (key, value) VALUES
                 ('since', ?1), ('libraries', ?2), ('favourites', ?3)",
                [changes.change.to_string(), readable, starred],
            )?;
        }
        db.commit()
    }
}

/// Asks the library for what changed (``library``: only these, from 0).
fn changes(
    url: &str,
    token: &str,
    since: i64,
    library: &[String],
) -> Result<Option<Changes>, String> {
    let mut request = libraries::agent_for_downloads()
        .get(format!("{url}/api/changes"))
        .query("since", since.to_string())
        .header("Cookie", &format!("{}={token}", libraries::SESSION_COOKIE));
    for id in library {
        request = request.query("library", id);
    }
    let mut response = request.call().map_err(|error| error.to_string())?;
    match response.status().as_u16() {
        200 => response
            .body_mut()
            .with_config()
            .limit(1 << 30)
            .read_json()
            .map(Some)
            .map_err(|error| error.to_string()),
        // Offline too long: the removals since are no longer kept.
        410 => Ok(None),
        status => Err(format!("{url}: {status}")),
    }
}

/// Brings the copy up to date: from the last change number, and libraries
/// new to the person from 0. After a year offline (410), anew.
pub fn pull(store: &mut Store, url: &str, token: &str) -> Result<(), String> {
    let known = store.libraries();
    let fresh = store.since() == 0;
    let Some(found) = changes(url, token, store.since(), &[])? else {
        store.clear().map_err(|error| error.to_string())?;
        return pull(store, url, token);
    };
    let new: Vec<String> = found
        .libraries
        .iter()
        .filter(|library| !fresh && !known.contains(library))
        .cloned()
        .collect();
    // New libraries whole first: the change number moves last, so an
    // interrupted sync asks for them again.
    if !new.is_empty()
        && let Some(whole) = changes(url, token, 0, &new)?
    {
        store
            .apply(&whole, true)
            .map_err(|error| error.to_string())?;
    }
    store
        .apply(&found, false)
        .map_err(|error| error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn changes(value: Value) -> Changes {
        serde_json::from_value(value).expect("an answer")
    }

    fn answer(change: i64, libraries: &[&str]) -> Value {
        json!({
            "change": change, "libraries": libraries, "removed": [], "items": [],
            "notes": [], "tags": [], "collections": [], "annotations": [], "views": []
        })
    }

    fn ids(store: &Store, kind: &str) -> Vec<String> {
        store
            .all(kind)
            .iter()
            .map(|record| record["id"].as_str().unwrap_or_default().to_owned())
            .collect()
    }

    #[test]
    fn kept_as_they_are_now_and_removed() {
        let mut store = Store::in_memory().unwrap();
        assert_eq!((store.since(), store.libraries()), (0, vec![]));
        let mut first = answer(7, &["own", "lab"]);
        first["items"] = json!([
            {"id": "p1", "library_id": "own", "title": "One", "files": [{"id": "f1"}, {"id": "f2"}]},
            {"id": "p2", "library_id": "lab", "title": "Two", "files": []}
        ]);
        first["notes"] = json!([{"id": "n1", "library_id": "lab", "text": "# Seminar"}]);
        first["tags"] = json!([{"id": "t1", "library_id": "lab", "name": "optics"}]);
        first["annotations"] = json!([
            {"id": "a1", "item_id": "p1", "file_id": "f1"},
            {"id": "a2", "item_id": "p1", "file_id": "f2"}
        ]);
        first["views"] = json!([{"item_id": "p2", "reading": {"page": 3}}]);
        store.apply(&changes(first), false).unwrap();
        assert_eq!(store.since(), 7);
        assert_eq!(store.libraries(), ["own", "lab"]);
        assert_eq!(ids(&store, "item"), ["p1", "p2"]);
        assert_eq!(store.get("view", "p2").unwrap()["reading"]["page"], 3);

        // Changed, a file removed (with its annotation), a tag deleted.
        let mut second = answer(9, &["own", "lab"]);
        second["items"] =
            json!([{"id": "p2", "library_id": "lab", "title": "Two, revised", "files": []}]);
        second["removed"] = json!([{"id": "f2", "kind": "file"}, {"id": "t1", "kind": "tag"}]);
        store.apply(&changes(second), false).unwrap();
        assert_eq!(store.get("item", "p2").unwrap()["title"], "Two, revised");
        assert_eq!(
            store.get("item", "p1").unwrap()["files"],
            json!([{"id": "f1"}])
        );
        assert_eq!(ids(&store, "annotation"), ["a1"]);
        assert!(ids(&store, "tag").is_empty());

        // Moved out and back in one change: removed, then as it is now.
        let mut moved = answer(10, &["own", "lab"]);
        moved["removed"] = json!([{"id": "p2", "kind": "item"}]);
        moved["items"] =
            json!([{"id": "p2", "library_id": "own", "title": "Two, revised", "files": []}]);
        store.apply(&changes(moved), false).unwrap();
        assert_eq!(store.get("item", "p2").unwrap()["library_id"], "own");

        // A paper removed: what went with it too.
        let mut gone = answer(11, &["own", "lab"]);
        gone["removed"] = json!([{"id": "p1", "kind": "item"}]);
        store.apply(&changes(gone), false).unwrap();
        assert!(ids(&store, "annotation").is_empty());
    }

    #[test]
    fn a_group_left_and_one_joined() {
        let mut store = Store::in_memory().unwrap();
        let mut first = answer(3, &["own", "lab"]);
        first["items"] = json!([{"id": "p1", "library_id": "lab", "files": []}]);
        first["notes"] = json!([{"id": "n1", "library_id": "lab"}]);
        first["views"] = json!([{"item_id": "p1"}]);
        store.apply(&changes(first), false).unwrap();

        // The lab left: its papers, notes and what went with them, gone.
        store.apply(&changes(answer(4, &["own"])), false).unwrap();
        assert!(ids(&store, "item").is_empty() && ids(&store, "note").is_empty());
        assert!(store.all("view").is_empty());

        // A library joined is taken in whole, without moving the number.
        let mut whole = answer(99, &["chair"]);
        whole["items"] = json!([{"id": "p9", "library_id": "chair", "files": []}]);
        store.apply(&changes(whole), true).unwrap();
        assert_eq!(ids(&store, "item"), ["p9"]);
        assert_eq!(
            (store.since(), store.libraries()),
            (4, vec!["own".to_owned()])
        );

        store.clear().unwrap();
        assert_eq!(store.since(), 0);
        assert!(ids(&store, "item").is_empty());
    }
}
