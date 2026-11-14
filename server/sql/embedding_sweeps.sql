-- The SQL paperus sends for: embedding sweeps (tests/test_sql.py)

SELECT pl.blob_sha256
FROM page_layouts pl
WHERE pl.version = %(version)s
  AND EXISTS
    (SELECT 1
     FROM files f
     WHERE f.blob_sha256 = pl.blob_sha256
       AND f.deleted_at IS NULL
       AND f.text_status = 'done')
  AND NOT EXISTS
    (SELECT 1
     FROM embedded_figures ef
     WHERE ef.blob_sha256 = pl.blob_sha256
       AND ef.model = %(vectors)s)
ORDER BY pl.created_at DESC
LIMIT %(limit)s;

SELECT DISTINCT chunks.sha256,
                chunks.text,
                chunks.tsv
FROM chunks
JOIN item_chunks ON item_chunks.chunk_sha256 = chunks.sha256
JOIN items ON items.id = item_chunks.item_id
WHERE items.deleted_at IS NULL
  AND NOT (EXISTS
             (SELECT embeddings.chunk_sha256
              FROM embeddings
              WHERE embeddings.model = %(model_1)s::VARCHAR
                AND embeddings.chunk_sha256 = chunks.sha256))
LIMIT %(param_1)s::INTEGER;

SELECT files.id
FROM files
WHERE files.text_status = %(text_status_1)s::VARCHAR
  AND files.deleted_at IS NULL
  AND NOT (EXISTS
             (SELECT versions.id
              FROM versions
              JOIN items ON items.id = versions.item_id
              WHERE versions.id = files.version_id
                AND items.deleted_at IS NOT NULL))
  AND NOT (EXISTS
             (SELECT embedded_files.file_id
              FROM embedded_files
              WHERE embedded_files.model = %(model_1)s::VARCHAR
                AND embedded_files.file_id = files.id))
ORDER BY files.id
LIMIT %(param_1)s::INTEGER;

SELECT notes.id
FROM notes
JOIN note_chunks ON note_chunks.note_id = notes.id
WHERE notes.deleted_at IS NULL
  AND NOT (EXISTS
             (SELECT embeddings.chunk_sha256
              FROM embeddings
              WHERE embeddings.model = %(model_1)s::VARCHAR
                AND embeddings.chunk_sha256 = note_chunks.chunk_sha256))
GROUP BY notes.id
ORDER BY notes.id
LIMIT %(param_1)s::INTEGER;
