# Third-party components

paperus itself is licensed under Apache-2.0 ([LICENSE](LICENSE)). These parts
come from others and keep their own licences.

## Shipped with paperus

| Component | Where | Licence |
| --- | --- | --- |
| [PDF.js](https://mozilla.github.io/pdf.js/) (pdfjs-dist) | Website: the PDF reader | Apache-2.0, [text](licenses/PDF.js-Apache-2.0.txt) |
| [marked](https://marked.js.org/) | Website: showing Markdown notes | MIT, [text](licenses/marked-MIT.txt) |
| [DOMPurify](https://github.com/cure53/DOMPurify) | Website: cleaning the HTML of shown notes | Apache-2.0 (or MPL-2.0), [text](licenses/DOMPurify-Apache-2.0.txt) |
| [KaTeX](https://katex.org/) with its fonts, and [marked-katex-extension](https://github.com/UziTech/marked-katex-extension) | Website: formulas in Markdown notes | MIT, texts: [KaTeX](licenses/KaTeX-MIT.txt), [extension](licenses/marked-katex-extension-MIT.txt) |
| [Literata](https://github.com/googlefonts/literata) | Website and logo: titles, headings, wordmark | SIL Open Font License 1.1, [text](licenses/Literata-OFL-1.1.txt) |
| [Atkinson Hyperlegible Next](https://www.brailleinstitute.org/freefont/) | Website: interface text | SIL Open Font License 1.1, [text](licenses/Atkinson-Hyperlegible-Next-OFL-1.1.txt) |
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

Metadata comes from doi.org, Crossref and DataCite at runtime, under their
terms of use.
