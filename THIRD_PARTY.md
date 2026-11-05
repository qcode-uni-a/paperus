# Third-party components

paperus itself is licensed under Apache-2.0 ([LICENSE](LICENSE)). These parts
come from others and keep their own licences.

## Shipped with paperus

| Component | Where | Licence |
| --- | --- | --- |
| [PDF.js](https://mozilla.github.io/pdf.js/) (pdfjs-dist) | Website: the PDF reader | Apache-2.0, [text](licenses/PDF.js-Apache-2.0.txt) |
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
| multilingual-e5-small | [Xenova/multilingual-e5-small](https://huggingface.co/Xenova/multilingual-e5-small) (ONNX export of intfloat/multilingual-e5-small) | MIT |

Metadata comes from doi.org, Crossref and DataCite at runtime, under their
terms of use.
