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

How a PDF's text is read now (#43): from its page layouts (fluent mode's,
`paperus.page_layout`), each piece's characters in reading order, one flow
across columns and pages, without margins, running headers and footers and
page numbers. Lines in a figure (its labels, ticks, legend) are left out;
captions are passages of their own, the text running on past them.
Passages of about 200 words (at most 350) are cut at sentence ends, a new
one at each section heading (after 30 words at least) and where a
reference list starts or ends (where entries follow its heading); each has
the page it starts on. Pages read by OCR are sections of their own, and
PDFs without layouts (too large or slow to lay out) are read page by page.
A change of the layout code (`page_layout.VERSION`) makes the layouts and
cuts the passages again, a few at a time; passages whose text stayed keep
their vectors.

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
  default (arctic-embed-m-v2; see the trials below). CPU is fine at group
  scale.
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

Vision-language models on the same pages (2026-11-13; PyTorch on the GPU,
fp16, a whole page each, for comparison only):

| model (licence)                        | en clean | en scan | de clean | de scan | GPU per page |
| -------------------------------------- | -------- | ------- | -------- | ------- | ------------ |
| Qwen3-VL-2B-Instruct (Apache-2.0)      | 0.84     | 0.95    | 0.99     | 0.99    | 26 s         |
| granite-docling-258M (Apache-2.0)      | 0.93     | 0.77    | 0.99     | 0.99    | 150 s (fp32) |
| PaddleOCR-VL 1.6 (Apache-2.0)          | 0.80     | 0.69    | 0.99     | 1.00    | 94 s         |

They read plain German pages as well as ours, but on English pages with
figures and formulas they loop (Qwen3-VL asked for LaTeX wrote
`\begin{tabular}` until the limit; plain text and a slight repetition
penalty helped), and they take 10 to 50 times as long on a GPU as ours on
a CPU. granite-docling gives only "!" in fp16 (an overflow; the RTX 2080
has no bf16). PaddleOCR-VL is made for regions cut out by a layout model,
not whole pages. Each would also need its own generation loop in ONNX
Runtime. Not adopted; worth another look for formulas, tables and
handwriting, which this test does not measure.

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

### Passages from page layouts (#43, 2026-11-14)

The 200 questions on the same library cut both ways, multilingual-e5-small
on a CPU, hybrid search without reranking: passages cut page by page
(a copy of the model trials' database) and from the page layouts (the dev
library after #43 and #53: one flow across columns and pages, without
running headers and figures' labels, captions apart, a passage per
section). Right paper first / in the top five / MRR@10:

| passages      | all                | detail (13)        | German (36)        | vague (37)         |
| ------------- | ------------------ | ------------------ | ------------------ | ------------------ |
| by page       | 0.79 / 0.94 / 0.85 | 0.92 / 1.00 / 0.95 | 0.58 / 0.78 / 0.68 | 0.70 / 0.95 / 0.81 |
| from layouts  | 0.78 / 0.94 / 0.85 | 0.69 / 0.92 / 0.78 | 0.56 / 0.86 / 0.67 | 0.81 / 0.92 / 0.87 |

Question by question the layouts put 11 papers first that pages did not
and 13 the other way (sign test p = 0.84): no difference. Vague questions
gained, three detail questions lost a few places (rank 1 → 3, 5, 7); in
the one looked at, the sentence asked about is in both cuts word for word,
in a passage of other surroundings. So the cleaner text costs search
nothing; what it brings is passages that read whole (no headers or plot
labels in mid-sentence, a paragraph over a page break in one).

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

### Embedding models and rerankers (2026-11-12)

100 questions now (56 more, again written from the same library, now 408
papers, 38,000 passages; 9 in German, 18 vague), hybrid search, the library
embedded on the GPU (RTX 2080 SUPER, fp16). Right paper first / in the top
five / MRR@10, without and with bge-reranker-v2-m3:

| model (licence)                    | without            | with reranking     | German first, without | GPU, whole library | CPU (int8, 20 threads) |
| ---------------------------------- | ------------------ | ------------------ | --------------------- | ------------------ | ---------------------- |
| **arctic-embed-m-v2** (Apache-2.0) | 0.89 / 1.00 / 0.94 | 0.89 / 0.98 / 0.93 | 8 of 9                | 4 min              | 5.5 passages/s         |
| multilingual-e5-small (MIT)        | 0.78 / 0.94 / 0.85 | 0.90 / 1.00 / 0.94 | 5 of 9                | 2 min              | 16.6 passages/s        |
| bge-m3 (MIT)                       | 0.84 / 0.99 / 0.90 | 0.90 / 0.98 / 0.94 | 6 of 9                |                    | 3.1 passages/s         |
| qwen3-embedding-0.6b (Apache-2.0)  | 0.82 / 1.00 / 0.90 | 0.92 / 0.99 / 0.95 | 7 of 9                | 13 min             | 2.1 passages/s         |
| embeddinggemma-2 (Apache-2.0)      | 0.78 / 0.99 / 0.87 | 0.91 / 0.98 / 0.94 | 7 of 9                | 6 min              | 4.0 passages/s         |
| embeddinggemma-300m (Gemma terms)  | 0.76 / 0.95 / 0.85 | 0.83 / 0.96 / 0.89 | 5 of 9                | 9 min              |                        |
| Qwen3-VL-Embedding-2B (Apache-2.0) | 0.84 / 0.98 / 0.90 | 0.91 / 0.99 / 0.94 | 5 of 9                | 30 min             |                        |

The last two were scored before the question set accepted a second paper
for one question (below); the others after. The same model scored twice
differs by up to 0.02, so differences below about 0.04 mean nothing.

- arctic-embed-m-v2, the default, is the best without reranking, and on a
  CPU faster than any other but multilingual-e5-small (a library this size
  in 2 hours, e5-small 40 minutes, EmbeddingGemma 2 2.6 hours,
  Qwen3-Embedding 5 hours).
- With reranking the reranker evens the models out: all land between 0.89
  and 0.92 first. Kept: arctic-embed-m-v2 as the default; the new ones
  stay choices, none better.
- EmbeddingGemma 300m is worse than its successor and under Gemma's own
  terms; dropped. Qwen3-VL-Embedding (text and images in one space; our own
  ONNX export of its language model) is no better on text, worse in
  German, and three times the size of Qwen3-Embedding; worth it only for
  searching figures.

Rerankers on two of the new models (before the question set's change; time
for the questions relative to bge-reranker-v2-m3 on the GPU):

| reranker (licence)                          | on Qwen3-Embedding | on EmbeddingGemma 2 | German first | time |
| ------------------------------------------- | ------------------ | ------------------- | ------------ | ---- |
| bge-reranker-v2-m3 (Apache-2.0)             | 0.91 / 0.99 / 0.94 | 0.89 / 0.98 / 0.92  | 7–8 of 9     | 1    |
| gte-multilingual-reranker-base (Apache-2.0) | 0.89 / 0.99 / 0.93 | 0.86 / 0.99 / 0.92  | 7 of 9       | 0.87 |
| Qwen3-Reranker-0.6B (Apache-2.0)            | 0.88 / 0.99 / 0.93 | 0.85 / 1.00 / 0.91  | 9 of 9       | 1.3  |

Qwen3-Reranker is a language model that answers "yes" or "no"; a
conversion to a classifier with one score (`tomaarsen/…-seq-cls`, in ONNX
by a third party) runs as an ordinary reranker, given its prompt template
and padding with its own pad token (the model scores the last token that
is not padding). It puts every German question first, the others no
better; not adopted.

All rerankers stop near 0.9 first. The misses are mostly second or third
place behind a paper that fits nearly as well (two 2019 reviews of
ultrastrong coupling; three papers on gate-based spin readout in silicon,
the question's "industrial transistor" the only difference), and the
rerankers miss different ones: what is left are fine distinctions, not a
reranker that cannot keep up. The question set now accepts both reviews.

### 200 questions (2026-11-13)

100 more questions on papers not asked about yet, mostly German and vague
ones: now 94 by meaning, 37 vague, 36 German, 20 by keyword, 13 on a detail
inside a paper. Right paper first / in the top five / MRR@10, and German
and vague questions first, without and with bge-reranker-v2-m3:

| model                     | without            | German / vague | with reranking     | German / vague |
| ------------------------- | ------------------ | -------------- | ------------------ | -------------- |
| **arctic-embed-m-v2**     | 0.91 / 0.99 / 0.94 | 0.94 / 0.81    | 0.92 / 0.99 / 0.95 | 0.86 / 0.89    |
| multilingual-e5-small     | 0.79 / 0.94 / 0.85 | 0.64 / 0.70    | 0.91 / 0.98 / 0.94 | 0.81 / 0.84    |
| bge-m3                    | 0.83 / 0.98 / 0.89 | 0.75 / 0.81    | 0.91 / 0.99 / 0.95 | 0.83 / 0.89    |
| qwen3-embedding-0.6b      | 0.83 / 0.99 / 0.90 | 0.78 / 0.78    | 0.92 / 0.99 / 0.95 | 0.83 / 0.89    |
| embeddinggemma-2          | 0.81 / 0.99 / 0.89 | 0.78 / 0.78    |                    |                |
| nemotron-3-embed-1b       | 0.68 / 0.89 / 0.76 | 0.61 / 0.81    | 0.89 / 0.96 / 0.92 | 0.83 / 0.86    |

(EmbeddingGemma 2 with reranking was not run.) Compared question by
question (sign test: of the questions only one of two puts first, how
many each wins, and how likely so uneven a split is between two equally
good ones):

- Without reranking arctic-embed-m-v2 beats every other model: 20 : 5
  against Qwen3-Embedding, 21 : 6 against bge-m3, 22 : 4 against
  EmbeddingGemma 2, 30 : 7 against e5-small (p ≤ 0.01 each). The others
  do not differ from each other.
- With reranking all four are the same (184, 183, 182, 181 first; p ≥ 0.55
  for every pair).
- The reranker barely helps arctic-embed-m-v2 (181 → 184 first; 14 : 11,
  p = 0.69) and costs it German questions (34 → 31 of 36 first) while
  helping vague ones (30 → 33 of 37). arctic without reranking is as good
  as any model with it.

So arctic-embed-m-v2 stays the default, and a server without a GPU, which
does not rerank by default ("auto"), loses little with it. The reranker
matters for the weaker models (e5-small 158 → 181 first).

NVIDIA's Nemotron 3 Embed 1B (July 2026, OpenMDW 1.1; 2048 dimensions,
which `halfvec` stores and could index up to 4000) in a third party's
ONNX export, fp16 on the GPU (22 minutes for the library; no int8, so on
a CPU slower than Qwen3-Embedding): the weakest here without reranking,
German especially (arctic-embed-m-v2 wins 52 : 6), and with it no better
(177 first; 12 : 5 for arctic with reranking, p = 0.14). Not adopted.
Whether the export loses quality was not checked.

### Figures by what they show (#36, 2026-11-14)

The dev library's PDFs after layout version 10: 3,198 figures found with
their captions (404 PDFs). 91 questions, written by looking at 66 figures
picked at random: 65 describe only the look (plot type, panels, colours,
markers, insets: "two stacked colormaps versus tunnel coupling, the top one
striped"), 20 name a concept ("a 1/f charge noise spectrum", "a honeycomb
charge stability diagram"), 6 mix both. Each question has one right
figure; meaning only (no keyword search, so the models compare fairly);
right figure first / in the top five / in the top ten, by kind:

| figures as vectors                                | look (65)          | concept (20)       | mixed (6)          |
| ------------------------------------------------- | ------------------ | ------------------ | ------------------ |
| caption (arctic-embed-m-v2: today's search)       | 0.09 / 0.22 / 0.26 | 0.15 / 0.35 / 0.35 | 0.33 / 0.67 / 0.67 |
| description written by Qwen3-VL-2B-Instruct       | 0.23 / 0.43 / 0.49 | 0.00 / 0.05 / 0.15 | 0.33 / 0.50 / 0.67 |
| SigLIP 2 so400m, image                            | 0.26 / 0.48 / 0.54 | 0.10 / 0.20 / 0.20 | 0.67 / 0.67 / 0.67 |
| Qwen3-VL-Embedding-2B, image                      | 0.40 / 0.63 / 0.68 | 0.10 / 0.15 / 0.25 | 0.67 / 0.67 / 0.83 |
| … image and caption in one vector                 | 0.28 / 0.49 / 0.54 | 0.20 / 0.45 / 0.55 | 0.83 / 0.83 / 0.83 |
| … the same, "caption only as context"             | 0.23 / 0.58 / 0.65 | 0.15 / 0.40 / 0.55 | 0.50 / 0.83 / 0.83 |
| … caption alone                                   | 0.17 / 0.35 / 0.43 | 0.25 / 0.45 / 0.55 | 0.50 / 0.67 / 0.67 |
| … best of image and caption (two vectors)         | 0.26 / 0.65 / 0.68 | 0.25 / 0.50 / 0.50 | 0.67 / 0.83 / 0.83 |
| … best of image and its panels                    | 0.35 / 0.58 / 0.68 | 0.05 / 0.10 / 0.20 | 0.67 / 0.67 / 0.83 |
| best of image and caption, top 20 reranked by Qwen3-VL-Reranker-2B on the image | **0.62 / 0.72 / 0.72** | 0.15 / 0.40 / 0.55 | 0.50 / 1.00 / 1.00 |
| … reranked on image and caption                   | 0.54 / 0.72 / 0.72 | 0.25 / 0.45 / 0.55 | 0.83 / 1.00 / 1.00 |

(The first 1,237 figures alone gave Qwen3-VL on the image 0.48 / 0.69 /
0.74 for the look questions: more figures, more lookalikes.)

- Captions hardly say how a figure looks: today's search finds the right
  one first for 9% of the look questions. Qwen3-VL-Embedding on the image
  is far ahead of SigLIP 2 (trained on photos) and of descriptions
  written by a small vision model and embedded as text.
- The reranker looking at each candidate with the question is the big
  step (0.40 → 0.62 first): it checks colours, layout and markers where
  one vector blurs them. The image size it sees (384, 512 or 768 px)
  makes no difference; it reorders only the 20 it gets, and every
  figure that reached them ended in the top five.
- Concept questions look weak, but a quantum-dot library has dozens of
  charge stability diagrams and band structures: looked at, the figure
  put first fits the question in about 7 of 10 (another paper's addition
  spectrum, another Chern-number phase diagram). One right figure per
  question undercounts them; keyword search (not used here) would add
  the captions' terms.
- The caption in the figure's vector helps concept questions and costs
  look questions; kept as a vector of its own (the caption's passage,
  as now) and the figure scored by the better of the two, both hold up.
  An instruction to use the caption "only as context" changes little.
- Panels: figures cut at blank rows and columns (1,228 of them, into
  4,130 panels, colour bars and legends kept with their panel) and each
  panel a vector of its own did not help: more lookalikes than focused
  matches. Qwen3-VL-2B-Instruct asked for each panel's box returns round
  guesses (an even 2×2 grid, a box over the top 60 %), at 3.3 s a figure:
  not usable. The misses are mostly composite figures described panel by
  panel and small figures with tiny text. Nor do panels bring more right
  figures to the reranker (the right one among the first 20 / 40 for look
  questions: image 0.74 / 0.77, image or a panel 0.74 / 0.80; image or
  caption 0.77 / 0.82, for concept questions 0.40 → 0.75 in the first 20
  with the caption). Detectors trained for panels are not open enough to
  ship: EXSCLAIM! (materials science) is GPL-3.0, YOLO-based ones AGPL,
  biomedical ones mostly for research only. Parked; making small panels
  legible (rendering every figure at the same scale) is the better lever.
- Speed (RTX 2080 SUPER, fp16): the image vectors 105 ms a figure, once at
  import; the reranker 67 ms a candidate at 384 px, of which preparing
  the image is half (0.76 of 1.5 s for 20), which needs no question and
  could be done at import: about 0.5 s for 20 candidates, less with the
  vision encoder's output kept too (not measured).

The same pair on text: the 200 questions on a copy of the model trials'
database (its passages cut by page; Qwen3-VL-Embedding's vectors of
2026-11-12, the questions encoded the same way), hybrid search, the
reranker's pool of 40 passages (at most two a paper) kept and reranked.
Right paper first / in the top five / MRR@10:

| embedding             | without            | bge-reranker-v2-m3 | Qwen3-VL-Reranker-2B |
| --------------------- | ------------------ | ------------------ | -------------------- |
| arctic-embed-m-v2     | 0.90 / 0.99 / 0.94 | 0.91 / 1.00 / 0.95 | 0.96 / 0.99 / 0.98   |
| Qwen3-VL-Embedding-2B | 0.88 / 0.99 / 0.93 | 0.93 / 0.99 / 0.96 | 0.97 / 0.99 / 0.98   |

Qwen3-VL-Embedding is as good as arctic-embed-m-v2 on text (as before,
within the noise), and its reranker better than bge on either: 0.96 to
0.97 first. It takes 56 ms a passage (RTX 2080 SUPER, fp16, PyTorch
without flash attention): 2.2 s for 40, but reranking only the first 10
keeps 0.96 / 0.99 / 0.97 in 0.56 s.

So one pair, Qwen3-VL-Embedding and Qwen3-VL-Reranker, could serve text
and figures in one space on a server with a GPU: text as good or better
than today, figures found by what they show (0.62 first, 0.72 in the top
five, against 0.09 / 0.22 by caption). Both are 2B models (about 4.4 GB
each at fp16): two at once need int4 weights on an 8 GB card. The ML
service runs ONNX only; the text part of the embedding model is exported
(`data/ocr-test/export_qwen3vl.py`), the vision part and the reranker are
not yet (onnx-community/Qwen3-VL-2B-Instruct-ONNX shows the split: vision
encoder, token embeddings, decoder).

Possible next steps: render each figure for the model at a fixed size
(longest side about 1,000 px; small single-column figures now come out
near 500 px); link a figure to the passages that mention it ("Fig. 3
shows …") so concept questions find it through the paragraph that
explains it; keyword search over captions as today.
