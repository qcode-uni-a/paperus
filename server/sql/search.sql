-- The SQL paperus sends for: search (tests/test_sql.py)

WITH q AS
  (SELECT websearch_to_tsquery('simple', %(query)s) AS tsq),
     visible AS NOT MATERIALIZED
  (SELECT 'paper' AS kind,
          fc.file_id AS source_id,
          fc.position,
          fc.page,
          fc.chunk_sha256,
          fc.in_references,
          f.version_id,
          i.id AS item_id,
          i.title AS item_title,
          fc.caption,
          f.blob_sha256,
          fc.figure
   FROM file_chunks fc
   JOIN files f ON f.id = fc.file_id
   JOIN versions v ON v.id = f.version_id
   JOIN items i ON i.id = v.item_id
   WHERE f.deleted_at IS NULL
     AND i.deleted_at IS NULL -- The archive only if asked for (or within one of its papers).

     AND (i.archived_at IS NULL
          OR %(archived)s
          OR CAST(%(item)s AS UUID) IS NOT NULL) -- Only libraries the person can read.

     AND i.library_id = ANY(CAST(%(libraries)s AS UUID[]))
     AND (cardinality(CAST(%(types)s AS text[])) = 0
          OR i.type = ANY(CAST(%(types)s AS text[]))) -- Within one paper only, if asked.

     AND (CAST(%(item)s AS UUID) IS NULL
          OR i.id = CAST(%(item)s AS UUID)) -- Figures (their captions) only, if asked.

     AND (NOT %(figures)s
          OR fc.caption)
     AND TRUE
   UNION ALL SELECT 'note',
                    nc.note_id,
                    nc.position,
                    NULL,
                    nc.chunk_sha256,
                    FALSE,
                    NULL,
                    NULL,
                    n.title,
                    FALSE,
                    NULL,
                    NULL
   FROM note_chunks nc
   JOIN notes n ON n.id = nc.note_id
   WHERE n.deleted_at IS NULL
     AND n.library_id = ANY(CAST(%(libraries)s AS UUID[]))
     AND (cardinality(CAST(%(types)s AS text[])) = 0
          OR 'note' = ANY(CAST(%(types)s AS text[])))
     AND CAST(%(item)s AS UUID) IS NULL
     AND NOT %(figures)s
     AND TRUE
   UNION ALL -- A paper's details: its title and abstract, with or without a file.
 SELECT 'details',
        i.id,
        0,
        NULL,
        ic.chunk_sha256,
        FALSE,
        NULL,
        i.id,
        i.title,
        FALSE,
        NULL,
        NULL
   FROM item_chunks ic
   JOIN items i ON i.id = ic.item_id
   WHERE i.deleted_at IS NULL
     AND (i.archived_at IS NULL
          OR %(archived)s
          OR CAST(%(item)s AS UUID) IS NOT NULL)
     AND i.library_id = ANY(CAST(%(libraries)s AS UUID[]))
     AND (cardinality(CAST(%(types)s AS text[])) = 0
          OR i.type = ANY(CAST(%(types)s AS text[])))
     AND (CAST(%(item)s AS UUID) IS NULL
          OR i.id = CAST(%(item)s AS UUID))
     AND NOT %(figures)s
     AND TRUE), keyword AS
  (SELECT vis.source_id,
          vis.position,
          vis.kind,
          row_number() OVER (
                             ORDER BY ts_rank_cd(c.tsv, q.tsq) DESC, vis.source_id, vis.position) AS rank
   FROM visible vis
   JOIN chunks c ON c.sha256 = vis.chunk_sha256,
                    q
   WHERE %(use_keyword)s
     AND c.tsv @@ q.tsq
   ORDER BY rank
   LIMIT %(candidates)s), -- As the vector indexes are made (``vector_index``): through them if
 -- there are.
 near AS MATERIALIZED
  (SELECT chunk_sha256,
          embedding::halfvec(16) <=> CAST(%(vector)s AS halfvec(16)) AS distance
   FROM embeddings
   WHERE %(use_meaning)s
     AND model = %(model)s
   ORDER BY distance
   LIMIT %(nearest)s), near_figures AS MATERIALIZED
  (SELECT blob_sha256,
          page,
          label,
          embedding::halfvec(16) <=> CAST(%(vector)s AS halfvec(16)) AS distance
   FROM figure_embeddings
   WHERE %(use_meaning)s
     AND model = %(model)s
   ORDER BY distance
   LIMIT %(nearest)s), by_nearest AS MATERIALIZED
  (SELECT vis.source_id,
          vis.position,
          vis.kind,
          n.distance IS NOT NULL AS near_text,
                                    least(coalesce(n.distance, 2), coalesce(nf.distance, 2)) AS distance
   FROM
     (SELECT 'paper' AS kind,
             fc.file_id AS source_id,
             fc.position,
             fc.page,
             fc.chunk_sha256,
             fc.in_references,
             f.version_id,
             i.id AS item_id,
             i.title AS item_title,
             fc.caption,
             f.blob_sha256,
             fc.figure
      FROM file_chunks fc
      JOIN files f ON f.id = fc.file_id
      JOIN versions v ON v.id = f.version_id
      JOIN items i ON i.id = v.item_id
      WHERE f.deleted_at IS NULL
        AND i.deleted_at IS NULL -- The archive only if asked for (or within one of its papers).

        AND (i.archived_at IS NULL
             OR %(archived)s
             OR CAST(%(item)s AS UUID) IS NOT NULL) -- Only libraries the person can read.

        AND i.library_id = ANY(CAST(%(libraries)s AS UUID[]))
        AND (cardinality(CAST(%(types)s AS text[])) = 0
             OR i.type = ANY(CAST(%(types)s AS text[]))) -- Within one paper only, if asked.

        AND (CAST(%(item)s AS UUID) IS NULL
             OR i.id = CAST(%(item)s AS UUID)) -- Figures (their captions) only, if asked.

        AND (NOT %(figures)s
             OR fc.caption)
        AND (fc.chunk_sha256 IN
               (SELECT chunk_sha256
                FROM near)
             OR (f.blob_sha256,
                 fc.page,
                 fc.figure) IN
               (SELECT blob_sha256,
                       page,
                       label
                FROM near_figures))
      UNION ALL SELECT 'note',
                       nc.note_id,
                       nc.position,
                       NULL,
                       nc.chunk_sha256,
                       FALSE,
                       NULL,
                       NULL,
                       n.title,
                       FALSE,
                       NULL,
                       NULL
      FROM note_chunks nc
      JOIN notes n ON n.id = nc.note_id
      WHERE n.deleted_at IS NULL
        AND n.library_id = ANY(CAST(%(libraries)s AS UUID[]))
        AND (cardinality(CAST(%(types)s AS text[])) = 0
             OR 'note' = ANY(CAST(%(types)s AS text[])))
        AND CAST(%(item)s AS UUID) IS NULL
        AND NOT %(figures)s
        AND nc.chunk_sha256 IN
          (SELECT chunk_sha256
           FROM near)
      UNION ALL -- A paper's details: its title and abstract, with or without a file.
 SELECT 'details',
        i.id,
        0,
        NULL,
        ic.chunk_sha256,
        FALSE,
        NULL,
        i.id,
        i.title,
        FALSE,
        NULL,
        NULL
      FROM item_chunks ic
      JOIN items i ON i.id = ic.item_id
      WHERE i.deleted_at IS NULL
        AND (i.archived_at IS NULL
             OR %(archived)s
             OR CAST(%(item)s AS UUID) IS NOT NULL)
        AND i.library_id = ANY(CAST(%(libraries)s AS UUID[]))
        AND (cardinality(CAST(%(types)s AS text[])) = 0
             OR i.type = ANY(CAST(%(types)s AS text[])))
        AND (CAST(%(item)s AS UUID) IS NULL
             OR i.id = CAST(%(item)s AS UUID))
        AND NOT %(figures)s
        AND ic.chunk_sha256 IN
          (SELECT chunk_sha256
           FROM near)) AS vis
   LEFT JOIN near n ON n.chunk_sha256 = vis.chunk_sha256
   LEFT JOIN near_figures nf ON nf.blob_sha256 = vis.blob_sha256
   AND nf.page = vis.page
   AND nf.label = vis.figure
   WHERE NOT vis.in_references), -- The nearest suffice if enough of them may be read (or they are all).
 enough AS MATERIALIZED
  (SELECT
     (SELECT count(*)
      FROM by_nearest
      WHERE near_text) >= %(candidates)s
   OR
     (SELECT count(*)
      FROM near) < %(nearest)s AS yes), meaning AS
  (-- A caption by the better of its text's vector and its figure's
 -- (a model that takes images: multimodal search).
 SELECT source_id,
        POSITION,
        kind,
        row_number() OVER (
                           ORDER BY distance, source_id, POSITION) AS rank
   FROM
     (SELECT source_id,
             POSITION,
             kind,
             distance
      FROM by_nearest
      WHERE
          (SELECT yes
           FROM enough)
      UNION ALL SELECT vis.source_id,
                       vis.position,
                       vis.kind,
                       least(e.embedding <=> CAST(%(vector)s AS halfvec), coalesce(fe.embedding <=> CAST(%(vector)s AS halfvec), 2))
      FROM visible vis
      JOIN embeddings e ON e.chunk_sha256 = vis.chunk_sha256
      AND e.model = %(model)s
      LEFT JOIN figure_embeddings fe ON fe.blob_sha256 = vis.blob_sha256
      AND fe.page = vis.page
      AND fe.label = vis.figure
      AND fe.model = %(model)s
      WHERE %(use_meaning)s
        AND NOT vis.in_references
        AND NOT
          (SELECT yes
           FROM enough)) AS compared
   ORDER BY rank
   LIMIT %(candidates)s),
                                        fused AS
  (SELECT source_id,
          POSITION,
          sum(CASE
                  WHEN kind = 'details'
                       AND SOURCE = 'keyword' THEN 2.0
                  ELSE 1.0
              END / (60 + rank)) AS score,
          bool_or(SOURCE = 'keyword') AS by_keyword,
          bool_or(SOURCE = 'meaning') AS by_meaning
   FROM
     (SELECT source_id,
             POSITION,
             kind,
             rank,
             'keyword' AS SOURCE
      FROM keyword
      UNION ALL SELECT source_id,
                       POSITION,
                       kind,
                       rank,
                       'meaning' AS SOURCE
      FROM meaning) AS candidates
   GROUP BY source_id,
            POSITION),
                                        visible_hits AS MATERIALIZED
  (SELECT 'paper' AS kind,
          fc.file_id AS source_id,
          fc.position,
          fc.page,
          fc.chunk_sha256,
          fc.in_references,
          f.version_id,
          i.id AS item_id,
          i.title AS item_title,
          fc.caption,
          f.blob_sha256,
          fc.figure
   FROM file_chunks fc
   JOIN files f ON f.id = fc.file_id
   JOIN versions v ON v.id = f.version_id
   JOIN items i ON i.id = v.item_id
   WHERE f.deleted_at IS NULL
     AND i.deleted_at IS NULL -- The archive only if asked for (or within one of its papers).

     AND (i.archived_at IS NULL
          OR %(archived)s
          OR CAST(%(item)s AS UUID) IS NOT NULL) -- Only libraries the person can read.

     AND i.library_id = ANY(CAST(%(libraries)s AS UUID[]))
     AND (cardinality(CAST(%(types)s AS text[])) = 0
          OR i.type = ANY(CAST(%(types)s AS text[]))) -- Within one paper only, if asked.

     AND (CAST(%(item)s AS UUID) IS NULL
          OR i.id = CAST(%(item)s AS UUID)) -- Figures (their captions) only, if asked.

     AND (NOT %(figures)s
          OR fc.caption)
     AND (fc.file_id,
          fc.position) IN
       (SELECT source_id,
               POSITION
        FROM fused)
   UNION ALL SELECT 'note',
                    nc.note_id,
                    nc.position,
                    NULL,
                    nc.chunk_sha256,
                    FALSE,
                    NULL,
                    NULL,
                    n.title,
                    FALSE,
                    NULL,
                    NULL
   FROM note_chunks nc
   JOIN notes n ON n.id = nc.note_id
   WHERE n.deleted_at IS NULL
     AND n.library_id = ANY(CAST(%(libraries)s AS UUID[]))
     AND (cardinality(CAST(%(types)s AS text[])) = 0
          OR 'note' = ANY(CAST(%(types)s AS text[])))
     AND CAST(%(item)s AS UUID) IS NULL
     AND NOT %(figures)s
     AND (nc.note_id,
          nc.position) IN
       (SELECT source_id,
               POSITION
        FROM fused)
   UNION ALL -- A paper's details: its title and abstract, with or without a file.
 SELECT 'details',
        i.id,
        0,
        NULL,
        ic.chunk_sha256,
        FALSE,
        NULL,
        i.id,
        i.title,
        FALSE,
        NULL,
        NULL
   FROM item_chunks ic
   JOIN items i ON i.id = ic.item_id
   WHERE i.deleted_at IS NULL
     AND (i.archived_at IS NULL
          OR %(archived)s
          OR CAST(%(item)s AS UUID) IS NOT NULL)
     AND i.library_id = ANY(CAST(%(libraries)s AS UUID[]))
     AND (cardinality(CAST(%(types)s AS text[])) = 0
          OR i.type = ANY(CAST(%(types)s AS text[])))
     AND (CAST(%(item)s AS UUID) IS NULL
          OR i.id = CAST(%(item)s AS UUID))
     AND NOT %(figures)s
     AND (i.id,
          0) IN
       (SELECT source_id,
               POSITION
        FROM fused)), -- The best few per paper (or note), so one paper cannot fill the list.
 capped AS
  (SELECT fused.*,
          row_number() OVER (PARTITION BY coalesce(vis.item_id, vis.source_id)
                             ORDER BY fused.score DESC, source_id, POSITION) AS nth
   FROM fused
   JOIN visible_hits vis USING (source_id,
                                POSITION))
SELECT vis.kind,
       vis.source_id,
       vis.position,
       vis.page,
       vis.in_references,
       vis.caption,
       vis.blob_sha256,
       vis.figure AS figure_label,
       c.text AS chunk_text,
       vis.version_id,
       vis.item_id,
       vis.item_title,
       fused.score,
       fused.by_keyword,
       fused.by_meaning,
       CASE
           WHEN fused.by_keyword THEN ts_headline('simple', replace(replace(replace(c.text, '&', '&amp;'), '<', '&lt;'), '>', '&gt;'), q.tsq, 'StartSel=<mark>, StopSel=</mark>, MaxWords=40, MinWords=15,' ' MaxFragments=2, FragmentDelimiter=" … "') -- Found by meaning only: no words to mark, so the passage's start.

           ELSE replace(replace(replace(CASE
                                            WHEN length(c.text) > 320 THEN left(c.text, 320) || '…'
                                            ELSE c.text
                                        END, '&', '&amp;'), '<', '&lt;'), '>', '&gt;')
       END AS snippet
FROM capped fused
JOIN visible_hits vis USING (source_id,
                             POSITION)
JOIN chunks c ON c.sha256 = vis.chunk_sha256,
                 q
WHERE fused.nth <= %(per_item)s
ORDER BY fused.score DESC,
         vis.source_id,
         vis.position
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

SET LOCAL hnsw.ef_search = 1000;

SET LOCAL plan_cache_mode = force_custom_plan;
