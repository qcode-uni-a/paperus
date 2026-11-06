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

| Method                                                                                                                               | Use                                         |
| ------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------- |
| Structure-aware (paragraphs/sections from GROBID or Docling, ~200–500 tokens, short paragraphs merged, long ones split with overlap) | **Default**                                 |
| Small-to-big (embed paragraphs, return the surrounding context)                                                                      | Via `get_passage(context=±n)` at query time |
| Cheap contextual retrieval (prepend `Title › Section › Subsection`)                                                                  | Default, before embedding                   |
| Late chunking (embed long context, pool per chunk)                                                                                   | Experiment later                            |
| LLM-generated chunk context (Anthropic's contextual retrieval)                                                                       | Not on the server (no LLM there)            |
| Semantic chunking                                                                                                                    | Only for unstructured text                  |

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

`paperus evaluate questions.json --user <name> [--each]` runs every question
in each mode (keyword, meaning, hybrid; one passage per paper) and prints
hit@1, hit@5 and MRR@10 per mode and per kind of question. The file is a JSON
list of `{"q": "…", "item_id": "…", "kind": "vague", "accept": ["…"]}`
(`accept`: other papers that also count as right). Question sets name papers
from someone's library, so they stay out of the repository.

### First run (2026-11-06)

44 questions written by Claude from the abstracts and passages of 40 papers
in one physicist’s library (376 papers), with multilingual-e5-small:

| mode    | hit@1 | hit@5 | MRR@10 |
| ------- | ----- | ----- | ------ |
| keyword | 0.18  | 0.20  | 0.19   |
| meaning | 0.68  | 0.91  | 0.78   |
| hybrid  | 0.66  | 0.91  | 0.77   |

- Keyword search needs every word in one passage, so it finds nothing for a
  question written as a sentence (2 of 25 paraphrases); it finds all five
  name-and-term queries ("SATIN protocol"). Hybrid is therefore almost
  exactly search by meaning.
- German questions about English papers: 2 of 4 in the top five.
- Trial: the keyword half matching any word that is not a stop word
  (ranked with `ts_rank`, normalised by length) reached 0.66 / 0.89 / 0.75
  on its own, but hybrid only 0.68 / 0.89 / 0.77. The questions share the
  abstracts' words, which favours keywords; not adopted until real
  questions from the group confirm it.

### Reranking trial (#9, 2026-11-06)

The same 44 questions: hybrid search's top 40 passages (at most 2 per
paper) reordered by a cross-encoder, int8 ONNX on the CPU (8 threads):

| reranker (licence)                          | languages | hit@1 | hit@5 | MRR@10 | per search |
| ------------------------------------------- | --------- | ----- | ----- | ------ | ---------- |
| none (hybrid)                               |           | 0.66  | 0.91  | 0.77   |            |
| ms-marco-MiniLM-L-6-v2 (Apache-2.0)         | English   | 0.75  | 0.89  | 0.82   | 1.7 s      |
| mxbai-rerank-xsmall-v1 (Apache-2.0)         | English   | 0.75  | 0.95  | 0.83   | 7 s        |
| gte-multilingual-reranker-base (Apache-2.0) | many      | 0.86  | 0.95  | 0.91   | 10 s       |
| bge-reranker-v2-m3 (Apache-2.0)             | many      | 0.86  | 0.98  | 0.91   | 21 s       |

The multilingual ones put the right paper first for 20 more questions in
100 (German questions too: 2 of 4 first), but take seconds per search on
a CPU. Ways to make it usable: fewer candidates (e.g. 20), shorter
passages, all cores, a GPU (#10), or reranking only when asked (a "sort
by relevance" step, or for AI assistants, which wait anyway). Jina's
reranker was left out: its licence forbids commercial use.

On the GPU (RTX 2080 SUPER, fp16, through paperus, library re-embedded with
the GPU's vectors): without reranking hybrid 0.64 / 0.86 / 0.75, with
bge-reranker-v2-m3 0.89 / 0.98 / 0.93 (meaning the same); German questions
3 of 4 first. About 0.6 s per search with reranking, 0.15 s without.
Adopted as "Automatic" (on with a GPU).
