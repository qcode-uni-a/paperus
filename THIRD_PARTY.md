# Third-party components

paperus itself is licensed under Apache-2.0 ([LICENSE](LICENSE)). These parts
come from others and keep their own licences.

## Shipped with paperus

| Component | Where | Licence |
| --- | --- | --- |
| [PDF.js](https://mozilla.github.io/pdf.js/) (pdfjs-dist) | Website: the PDF reader | Apache-2.0, [text](licenses/PDF.js-Apache-2.0.txt) |
| PDF.js's own files, shipped with it (`web/static/pdfjs/`, copied by `web/scripts/pdfjs-assets.js`): JBIG2 decoder (from PDFium), OpenJPEG, qcms; the Foxit standard fonts; Adobe's character maps; a colour profile | Website: drawing scans and PDFs without embedded fonts | BSD-3-Clause, BSD-2-Clause, MIT, BSD-3-Clause, BSD-3-Clause, CC0-1.0, as given in each folder's `LICENSE*` files, which are shipped with them |
| [marked](https://marked.js.org/) | Website: showing Markdown notes | MIT, [text](licenses/marked-MIT.txt) |
| [DOMPurify](https://github.com/cure53/DOMPurify) | Website: cleaning the HTML of shown notes | Apache-2.0 (or MPL-2.0), [text](licenses/DOMPurify-Apache-2.0.txt) |
| [KaTeX](https://katex.org/) with its fonts, and [marked-katex-extension](https://github.com/UziTech/marked-katex-extension) | Website: formulas in Markdown notes | MIT, texts: [KaTeX](licenses/KaTeX-MIT.txt), [extension](licenses/marked-katex-extension-MIT.txt) |
| [Literata](https://github.com/googlefonts/literata) | Website, homepage and logo: titles, headings, wordmark | SIL Open Font License 1.1, [text](licenses/Literata-OFL-1.1.txt) |
| [Atkinson Hyperlegible Next](https://www.brailleinstitute.org/freefont/) | Website and homepage: interface text | SIL Open Font License 1.1, [text](licenses/Atkinson-Hyperlegible-Next-OFL-1.1.txt) |
| [Procrastinate](https://github.com/procrastinate-org/procrastinate) database schema, copied into `server/src/paperus/migrations/procrastinate_3.10.0.sql` | Server: job queue tables | MIT |

The container images and packages also contain their Python and JavaScript
dependencies, each under its own licence; they are listed in
`server/uv.lock`, `ml/uv.lock`, `web/package-lock.json` and
`client/package-lock.json`.

## Downloaded at runtime

The machine learning service downloads models from Hugging Face on first use;
they are not part of paperus.

| Model | Source | Licence |
| --- | --- | --- |
| BGE-M3 | [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) | MIT |
| BGE-M3 int8 | [Xenova/bge-m3](https://huggingface.co/Xenova/bge-m3) (ONNX export of BAAI/bge-m3) | MIT |
| Snowflake Arctic Embed M/L v2.0 | [Snowflake/snowflake-arctic-embed-m-v2.0](https://huggingface.co/Snowflake/snowflake-arctic-embed-m-v2.0), [-l-v2.0](https://huggingface.co/Snowflake/snowflake-arctic-embed-l-v2.0) | Apache-2.0 |
| GTE multilingual base | [onnx-community/gte-multilingual-base](https://huggingface.co/onnx-community/gte-multilingual-base) (ONNX export of Alibaba-NLP/gte-multilingual-base) | Apache-2.0 |
| multilingual-e5 small/base/large | [Xenova/multilingual-e5-small](https://huggingface.co/Xenova/multilingual-e5-small), [-base](https://huggingface.co/Xenova/multilingual-e5-base), [-large](https://huggingface.co/Xenova/multilingual-e5-large) (ONNX exports of intfloat/multilingual-e5-*) | MIT |
| BGE reranker v2 m3 | [onnx-community/bge-reranker-v2-m3-ONNX](https://huggingface.co/onnx-community/bge-reranker-v2-m3-ONNX) (ONNX export of BAAI/bge-reranker-v2-m3) | Apache-2.0 |
| GTE multilingual reranker base | [onnx-community/gte-multilingual-reranker-base](https://huggingface.co/onnx-community/gte-multilingual-reranker-base) | Apache-2.0 |
| ms-marco-MiniLM-L-6-v2 | [cross-encoder/ms-marco-MiniLM-L-6-v2](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L-6-v2) | Apache-2.0 |
| PP-OCRv6 small (text lines, reading) | [PaddlePaddle/PP-OCRv6_small_det_onnx](https://huggingface.co/PaddlePaddle/PP-OCRv6_small_det_onnx), [PaddlePaddle/PP-OCRv6_small_rec_onnx](https://huggingface.co/PaddlePaddle/PP-OCRv6_small_rec_onnx) | Apache-2.0 |

The OCR steps in `ml/src/paperus_ml/ocr.py` (finding and reading lines)
follow [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) and
[RapidOCR](https://github.com/RapidAI/RapidOCR) (both Apache-2.0), written
anew for paperus.

Metadata comes from doi.org, Crossref and DataCite at runtime, under their
terms of use; where a paper has open copies (and its arXiv version) from
OpenAlex and Unpaywall, open-access PDFs from arXiv and the places those
list.
