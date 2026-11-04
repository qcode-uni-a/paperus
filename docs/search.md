# Search

## What is indexed

- Full text of papers and other files, split into chunks.
- Notes (Markdown, split by heading or paragraph).
- Annotations: highlighted text plus the comment, linked to the passage.
- Optionally tags and collection descriptions.

Every chunk carries owner and visibility; the permission filter runs inside
the database query, so private notes appear only for their author and that
author's AI assistant.

## Chunking

| Method | Use |
| --- | --- |
| Structure-aware (paragraphs/sections from GROBID or Docling, ~200–500 tokens, short paragraphs merged, long ones split with overlap) | **Default** |
| Small-to-big (embed paragraphs, return the surrounding context) | Via `get_passage(context=±n)` at query time |
| Cheap contextual retrieval (prepend `Title › Section › Subsection`) | Default, before embedding |
| Late chunking (embed long context, pool per chunk) | Experiment later |
| LLM-generated chunk context (Anthropic's contextual retrieval) | Not on the server (no LLM there) |
| Semantic chunking | Only for unstructured text |

Figure and table captions, abstracts and equations are separate chunk types.

## Retrieval

1. Hybrid: Postgres full-text search + pgvector, merged with reciprocal rank
   fusion. Exact terms (gene names, acronyms, dataset names) need keywords.
2. Rerank the top ~50 with a cross-encoder (e.g. bge-reranker).
3. Return passages with stable IDs (file UUID + chunk position, e.g.
   `0194f3c2-…#p5.para3`; not the bare chunk hash, which several files can
   share), page, snippet, score
   and a deep link that opens the reader at the highlighted passage.

Query rewriting (HyDE, multi-query) is left to the user's AI client, which can
call `search` several times. LLM-built structures (RAPTOR, GraphRAG) are out of
scope.

## Models

- Chunk embeddings: open model on the server, configurable, multilingual
  default (BGE-M3 or Qwen3-Embedding). CPU is fine at group scale.
  Optional OpenAI-compatible endpoint for admins (e.g. a university service).
- Store the model ID with every vector; a model change triggers a background
  re-index.
- Paper-level vectors for "similar papers": SPECTER2. Fetch precomputed ones
  from Semantic Scholar by DOI (`embedding.specter_v2`; check licence terms for
  bulk data), compute locally for papers it does not know.

Rough cost: a 10-page paper ≈ 8,000 tokens ≈ 20–40 chunks; a 10,000-paper
library is a one-off job of a few hours on CPU. One embedding (1,024 dims) is
4 KB as float32, 1–2 KB as float16/int8.

## Related papers (later)

Compute on ingest: nearest SPECTER2 neighbours above a threshold plus direct
citations from OpenAlex. Show a "Related" list per item first; a graph view per
collection later (Cytoscape.js or Sigma.js).

## Results UI

Notes and passages together with a type label; filters "Papers", "My notes",
"Group notes"; a note hit shows its paper, a paper hit shows "3 notes on this
paper"; AI-written notes labelled and filterable.

Non-generative "AI" features in the web UI: search by meaning, similar papers,
duplicate detection, topic clustering of a collection.

## Evaluation

Build a test set early: ~50 real questions from the group with the paragraphs
that answer them. Measure recall@10 and compare chunking/model choices on our
own data. Run the same set through several AI clients for the MCP path.
