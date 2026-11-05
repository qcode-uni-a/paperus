# To do

Smaller tasks noted along the way; larger plans live in the other documents.

## Search

- **Embedding speed.** bge-m3 in fp32 embeds about 1.5 chunks/s on a
  24-core CPU (measured 2026-11-05), so a 10,000-paper library would take
  days, not hours as estimated in [search.md](search.md). Compare int8
  exports, batch sizes and thread settings, and a smaller model.
