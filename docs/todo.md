# To do

Smaller tasks noted along the way; larger plans live in the other documents.

## Search

- **Exclude references from search by meaning.** A paper's reference list
  matches many queries by meaning (titles of other papers) and drowns out
  its own text. Detect the references section (heading "References",
  "Bibliography", "Literatur", …, or GROBID/Docling later), mark those
  chunks with a type, and leave them out of embedding and meaning search;
  keyword search can keep them (useful for "who cites X").
- **Embedding speed.** bge-m3 in fp32 embeds about 1.5 chunks/s on a
  24-core CPU (measured 2026-11-05), so a 10,000-paper library would take
  days, not hours as estimated in [search.md](search.md). Compare int8
  exports, batch sizes and thread settings, and a smaller model.
