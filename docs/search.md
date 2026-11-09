# Search

## What is indexed

- Full text of papers and other files, split into chunks; scanned pages
  and images by their text read with OCR (below).
- Each paper's details: its title and abstract as one more passage
  (`item_chunks`, kept current on every change by `paperus.details`), so a
  paper is found by them with or without a file. A keyword match there
  counts double in the fusion (`DETAILS_WEIGHT`); one by meaning counts
  like any passage (a title and abstract match many questions loosely).
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

### OCR (#26, 2026-11-06)

Scanned pages have no text layer. Pages of a PDF with fewer than 20
characters, and images (PNG, JPEG, TIFF, WebP), are rendered at 200 dpi
and read by the ML service in the background (job queue `ocr`, one file at
a time); the text is kept per page of the file's contents (`ocr_pages`), so
reading a file again or a copy of it needs no OCR. The rest of the PDF is
searchable at once.

Trial: 8 pages of our papers (rendered, so their text layer is the right
answer) and 3 German pages with umlauts and ß, each clean and as a "scan"
(tilted 0.8°, blurred, noise, JPEG); share of the page's words read right:

| engine (licence)                              | en clean | en scan | de clean | de scan | CPU per page |
| --------------------------------------------- | -------- | ------- | -------- | ------- | ------------ |
| PP-OCRv5 Latin, RapidOCR (Apache-2.0)         | 0.96     | 0.94    | 0.96     | 0.99    | 3.3 s        |
| PP-OCRv6 small, RapidOCR (Apache-2.0)         | 0.96     | 0.96    | 0.96     | 0.97    | 2.4 s        |
| PP-OCRv6 medium, RapidOCR (Apache-2.0)        | 0.96     | 0.96    | 0.92     | 0.98    | 8.3 s        |
| docTR (OnnxTR) fast + PARSeq (Apache-2.0)     | 0.95     | 0.95    | 0.86     | 0.86    | 15.8 s       |
| docTR (OnnxTR) DBNet + CRNN (Apache-2.0)      | 0.95     | 0.94    | 0.86     | 0.86    | 2.5 s        |
| PP-OCRv6 small, without the line flipper      | 0.96     | 0.96    | 1.00     | 1.00    | 2.7 s        |
| **ours**: PP-OCRv6 small in the ML service    | 0.96     | 0.96    | 1.00     | 0.995   | 3.0 s        |

- docTR's standard models drop umlauts. RapidOCR's classifier for upside
  down lines turned some widely spaced lines over and garbled them; without
  it German was read without a mistake. Missing English words are mostly
  in formulas.
- RapidOCR orders lines top to bottom across the page, mixing the columns
  of a paper line by line. Ours finds columns (a recursive XY cut on the
  line boxes, after turning back the page's tilt) and reads them one after
  the other, so passages stay whole.
- Adopted: PP-OCRv6 small (31 MB) with PaddlePaddle's settings, our own
  steps in `ml/src/paperus_ml/ocr.py` (no RapidOCR dependency; the same
  model handling, CPU or GPU, as the other models). Handwriting is read
  poorly.

### Passage size and overlap (#11, 2026-11-07)

The same 44 questions on a copy of the library, with arctic-embed-m-v2
(fp16, GPU), each variant re-cut and re-embedded; "overlap" repeats the
previous passage's last words at the start of the next (within a page):

| passages (words)        | passages | hybrid hit@1 / hit@5 / MRR | with reranking     |
| ----------------------- | -------- | -------------------------- | ------------------ |
| **200, at most 350**    | 40,470   | 0.82 / 0.98 / 0.87         | 0.82 / 0.98 / 0.90 |
| 120                     | 65,979   | 0.91 / 0.98 / 0.95         | 0.82 / 1.00 / 0.89 |
| 150                     | 53,013   | 0.89 / 0.95 / 0.92         | 0.77 / 1.00 / 0.86 |
| 300                     | 28,538   | 0.80 / 0.98 / 0.87         | 0.84 / 0.98 / 0.91 |
| 400                     | 22,262   | 0.80 / 0.98 / 0.88         | 0.84 / 0.98 / 0.90 |
| 200 across pages        | 39,467   | 0.82 / 0.98 / 0.87         | 0.84 / 0.98 / 0.91 |
| 200, overlap 50         | 40,470   | 0.82 / 0.98 / 0.89         | 0.89 / 1.00 / 0.93 |
| 200, overlap 100        | 40,470   | 0.91 / 0.98 / 0.94         | 0.84 / 1.00 / 0.91 |
| 120, overlap 40         | 65,979   | 0.89 / 0.98 / 0.92         | 0.89 / 1.00 / 0.93 |
| 150, overlap 50         | 53,013   | 0.80 / 0.98 / 0.88         | 0.86 / 1.00 / 0.92 |

One question is 0.023. Compared question by question with the default:

- Without reranking, overlap 100 puts 4 more papers first and none fewer
  (7 better, 1 worse); 120-word passages 5 more and 1 fewer. With
  reranking these gains mostly vanish (overlap 100: 3 better, 2 worse).
- With reranking, overlap 50 puts 4 more first and 1 fewer; 120 words with
  overlap 40 is as good, but needs 63% more vectors.
- No variant is better in both modes, and 7 of 1 is not yet sure (a sign
  test gives about 0.07). Larger passages and joining pages change little.
- Overlap adds no vectors, only a quarter to half more words to embed and
  store; it repeats text in results (to be trimmed when showing them).

Not adopted yet: overlap (50–100 words) is the candidate, to be confirmed
with real questions from the group, more of them vague and German.

### Vector index (#37, 2026-11-07)

Search by meaning compares the question with every visible passage's
vector (exact). Measured with pgvector 0.8.7 in the development database
(Ryzen 9 3900XT, Postgres defaults, up to 4 parallel workers): 341,650
real passage vectors from the trials above (arctic-embed-m-v2, 768
dimensions, `halfvec`), grown to a million with slightly varied copies;
the 44 questions' vectors; the best 40 passages, as search takes them.
"Filtered" keeps a tenth of the rows (one person's share of a large
server). Recall is the share of the exact best 40 found.

| passages | table | exact | exact, filtered | HNSW build | index |
| -------- | ----- | ----- | --------------- | ---------- | ----- |
| 100,000 | 156 MB | 27 ms | 19 ms | 34 s | 195 MB |
| 300,000 | 469 MB | 69 ms | 49 ms | 106 s | 585 MB |
| 1,000,000 | 1.6 GB | 241 ms | 177 ms | 9 min | 2.0 GB |

HNSW (`m = 16`, `ef_construction = 64`), median time and recall by
`hnsw.ef_search`; filtered with `hnsw.iterative_scan = relaxed_order`:

| passages | ef 40 | ef 100 | ef 200 | ef 400 | filtered, ef 100 | filtered, ef 400 |
| -------- | ----- | ------ | ------ | ------ | ---------------- | ---------------- |
| 100,000 | 0.87, 2 ms | 0.94, 1 ms | 0.99, 2 ms | 1.00, 4 ms | 0.93, 6 ms | 0.95, 7 ms |
| 300,000 | 0.82, 3 ms | 0.94, 3 ms | 0.97, 4 ms | 1.00, 6 ms | 0.93, 9 ms | 0.94, 9 ms |
| 1,000,000 | 0.85, 4 ms | 0.95, 3 ms | 0.97, 5 ms | 0.97, 9 ms | 0.93, 11 ms | 0.95, 13 ms |

- One physicist's 376 papers are 40,000 passages (about 100 a paper), so
  exact search stays under a tenth of a second up to about 3,000 papers a
  person can see, and a quarter second at 10,000. No index needed for a
  group; for a department-sized server, HNSW is 20–50 times faster and
  misses about 1 in 20 of the best 40 (the reranker then orders them).
- The index is larger than the vectors (2 GB a million) and should fit
  in memory. Built in one process it takes 9 minutes a million. A
  parallel build needs its graph in shared memory (`/dev/shm`), which
  Docker limits to 64 MB; compose now gives Postgres 1 GB
  (`shm_size`). With 4 workers 300,000 passages take 29 s instead of
  106 s; a million needs about 2.2 GB (`shm_size` and
  `maintenance_work_mem` both raised), otherwise the build falls back
  to adding passages one by one when the graph outgrows memory and is
  no faster (10 minutes with 900 MB).
- Not yet built: search's query joins the passages a person can see
  first, which an HNSW index cannot serve as it is; it would need to ask
  the index for the nearest passages of one model and filter after
  (iterative scan), with a partial index per model.

### Titles and abstracts (2026-11-09)

Each paper's title and abstract became one more passage (see "What is
indexed"). On the 44 questions, without reranking:

| Mode, questions | Before (hit@1 / hit@5 / MRR) | Details, both kinds of match ×2 | Details, keyword matches ×2 |
| --- | --- | --- | --- |
| Hybrid, all | 0.66 / 0.89 / 0.76 | 0.64 / 0.91 / 0.76 | **0.68 / 0.93 / 0.78** |
| Hybrid, meaning | 0.64 / 0.92 / 0.76 | 0.60 / 0.84 / 0.71 | 0.68 / 0.92 / 0.78 |
| Hybrid, German | 0.25 / 0.25 / 0.25 | 0.75 / 1.00 / 0.83 | 0.25 / 0.75 / 0.40 |
| Meaning, all | 0.68 / 0.89 / 0.77 | 0.57 / 0.91 / 0.72 | 0.70 / 0.93 / 0.79 |

Weighting matches by meaning too lets summaries (which match many questions
loosely) push the passage that answers down; weighting keyword matches only
is better or equal on every kind of question, and kept.
