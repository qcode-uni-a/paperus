-- The SQL paperus sends for: similar papers (tests/test_sql.py)

SELECT i.id
FROM items i
WHERE i.deleted_at IS NULL
  AND (i.archived_at IS NULL
       OR i.id = %(item)s)
  AND i.library_id = ANY(CAST(%(libraries)s AS UUID[]))
  AND NOT EXISTS
    (SELECT 1
     FROM paper_vectors pv
     WHERE pv.item_id = i.id
       AND pv.model = %(model)s
       AND pv.change = i.change)
ORDER BY i.id;

WITH this AS
  (SELECT pv.embedding,

     (SELECT e.embedding
      FROM item_chunks ic
      JOIN embeddings e ON e.chunk_sha256 = ic.chunk_sha256
      AND e.model = %(model)s
      WHERE ic.item_id = %(item)s) AS details
   FROM paper_vectors pv
   WHERE pv.item_id = %(item)s
     AND pv.model = %(model)s
     AND pv.embedding IS NOT NULL),
     others AS
  (SELECT pv.item_id,
          1 - (pv.embedding <=> this.embedding) AS average,
          1 - (de.embedding <=> this.details) AS details
   FROM this,
        items i
   JOIN paper_vectors pv ON pv.item_id = i.id
   AND pv.model = %(model)s
   AND pv.embedding IS NOT NULL
   LEFT JOIN item_chunks ic ON ic.item_id = i.id
   LEFT JOIN embeddings de ON de.chunk_sha256 = ic.chunk_sha256
   AND de.model = %(model)s
   WHERE i.deleted_at IS NULL
     AND i.archived_at IS NULL
     AND i.id <> %(item)s
     AND i.library_id = ANY(CAST(%(libraries)s AS UUID[])))
SELECT item_id,
       0.7 * average + 0.3 * coalesce(details, average) AS similarity
FROM others
ORDER BY similarity DESC,
         item_id
LIMIT %(limit)s;

SELECT authorships.item_id,
       authorships.position,
       authorships.author_id,
       authorships.written,
       authorships.key,
       authorships.source,
       authorships.affiliation,
       authorships.orcid,
       authorships.openalex_id
FROM authorships
WHERE authorships.item_id IN (__[POSTCOMPILE_primary_keys])
ORDER BY authorships.position;

SELECT collection_items.item_id,
       collection_items.collection_id,
       collection_items.added_by,
       collection_items.created_at,
       collections_1.id,
       collections_1.created_at,
       collections_1.library_id,
       collections_1.name,
       collections_1.description,
       collections_1.parent_id,
       collections_1.rules,
       collections_1.created_by,
       collections_1.change
FROM collection_items
JOIN collections AS collections_1 ON collections_1.id = collection_items.collection_id
WHERE collection_items.item_id IN (__[POSTCOMPILE_primary_keys]);

SELECT favourites.item_id,
       favourites.user_id,
       favourites.created_at
FROM favourites
WHERE favourites.item_id IN (__[POSTCOMPILE_primary_keys]);

SELECT files.version_id,
       files.id,
       files.created_at,
       files.blob_sha256,
       files.role,
       files.filename,
       files.media_type,
       files.source,
       files.uploaded_by,
       files.text_status,
       files.text_error,
       files.ocr_status,
       files.cover_pages,
       files.file_marks,
       files.deleted_at,
       files.deleted_by,
       blobs_1.sha256,
       blobs_1.size,
       blobs_1.created_at
FROM files
JOIN blobs AS blobs_1 ON blobs_1.sha256 = files.blob_sha256
WHERE files.version_id IN (__[POSTCOMPILE_primary_keys])
ORDER BY files.id;

SELECT groups.id,
       groups.parent_id
FROM groups;

SELECT identifiers.version_id,
       identifiers.id,
       identifiers.created_at,
       identifiers.scheme,
       identifiers.value
FROM identifiers
WHERE identifiers.version_id IN (__[POSTCOMPILE_primary_keys])
ORDER BY identifiers.id;

SELECT item_tags.item_id,
       item_tags.tag_id,
       item_tags.source,
       item_tags.added_by,
       item_tags.created_at,
       tags_1.id,
       tags_1.created_at,
       tags_1.library_id,
       tags_1.name,
       tags_1.color,
       tags_1.description,
       tags_1.change
FROM item_tags
JOIN tags AS tags_1 ON tags_1.id = item_tags.tag_id
WHERE item_tags.item_id IN (__[POSTCOMPILE_primary_keys]);

SELECT items.id,
       items.created_at,
       items.library_id,
       items.type,
       items.title,
       items.year,
       items.issued_from,
       items.issued_to,
       items.first_author,
       items.journal,
       items.file_wanted,
       items.open_access_tried_at,
       items.open_access_error,
       items.published_checked_at,
       items.errata_checked_at,
       items.cited_by_count,
       items.citations_checked_at,
       items.archived_at,
       items.references_checked_at,
       items.references_source,
       items.authors_key,
       items.authors_linked,
       items.authors_checked_at,
       items.abstract,
       items.overrides,
       items.links,
       items.added_by,
       items.change,
       items.changed_at,
       items.deleted_at,
       items.deleted_by
FROM items
WHERE items.id = %(pk_1)s::UUID;

SELECT items.id,
       items.created_at,
       items.library_id,
       items.type,
       items.title,
       items.year,
       items.issued_from,
       items.issued_to,
       items.first_author,
       items.journal,
       items.file_wanted,
       items.open_access_tried_at,
       items.open_access_error,
       items.published_checked_at,
       items.errata_checked_at,
       items.cited_by_count,
       items.citations_checked_at,
       items.archived_at,
       items.references_checked_at,
       items.references_source,
       items.authors_key,
       items.authors_linked,
       items.authors_checked_at,
       items.abstract,
       items.overrides,
       items.links,
       items.added_by,
       items.change,
       items.changed_at,
       items.deleted_at,
       items.deleted_by
FROM items
WHERE items.id IN (__[POSTCOMPILE_id_1]);

SELECT libraries.group_id,
       libraries.id
FROM libraries
WHERE libraries.group_id IN (__[POSTCOMPILE_group_id_1]);

SELECT libraries.id
FROM libraries
WHERE libraries.user_id = %(user_id_1)s::UUID;

SELECT memberships.group_id,
       memberships.role
FROM memberships
WHERE memberships.user_id = %(user_id_1)s::UUID;

SELECT system_settings.key,
       system_settings.value,
       system_settings.updated_at
FROM system_settings
WHERE system_settings.key = %(pk_1)s::VARCHAR;

SELECT users.id,
       users.created_at,
       users.username,
       users.password_hash,
       users.is_admin,
       users.default_library_id,
       users.seen_hints,
       users.last_login_at,
       users.last_active_at,
       users.deactivated_at,
       users.oidc_subject,
       users.avatar_type,
       users.avatar_version,
       users.handed_over,
       users.display_name,
       users.orcid,
       users.name_format
FROM users
JOIN login_sessions ON login_sessions.user_id = users.id
WHERE login_sessions.token_hash = %(token_hash_1)s
  AND login_sessions.expires_at > %(expires_at_1)s::TIMESTAMP WITH TIME ZONE
  AND users.deactivated_at IS NULL;

SELECT versions.item_id,
       versions.id,
       versions.created_at,
       versions.kind,
       versions.label,
       versions.csl,
       versions.metadata_source,
       versions.pinned,
       versions.created_by
FROM versions
WHERE versions.item_id IN (__[POSTCOMPILE_primary_keys])
ORDER BY versions.id;
