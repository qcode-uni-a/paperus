# Decisions and open questions

## Decided

| Topic | Decision | Why |
| --- | --- | --- |
| Name | paperUs (`paperus`) | "papers for us", sounds like papyrus; free on PyPI and npm. Domains not registered yet, on purpose. A small, unrelated GitHub project `Naridon-Inc/paperus` exists |
| Repository | In the university group's GitHub organization, repo `paperus` | Can be transferred later; redirects keep working |
| Relation to Zotero | Standalone, not built on Zotero; full Zotero import | Own data model for groups, versions, search; borrow ideas freely |
| Scope | Sources first (papers, lectures, meetings) and notes about them | Avoid becoming a Notion/Obsidian clone |
| AI | Bring your own AI via MCP; no LLM calls from the server | Vendor neutral, data stays on the server, cheaper |
| Server-side models | Embeddings, reranker, OCR only, open models, configurable | Needed for search; runs on CPU |
| Server language | Python (FastAPI); TypeScript for frontend and extension; Rust via PyO3 later if measured | The processing and model ecosystem is Python |
| Database | Postgres + pgvector, queue in Postgres | One service to run; permission filters in SQL |
| PDF fetching | Server: open access only; browser: user's session; manual fallback | Licences, campus IP blocks |
| IDs | UUIDv7 for every record; SHA-256 only for blobs and chunks | Same bytes can be different files; IDs needed before an upload ends; hashes reveal content; stable links |
| Licence | Apache-2.0 for everything (server and integrations) | Allows every later use (hosted version, other universities, companies); can still move to AGPL later, not the other way round; patent grant over MIT |
| Hosting | Stage 0: local on the developer's machine. Stage 1: a group machine at the university, VPN only, username and password login. Stage 2: a small VM from the computing centre for the pilot | Start without waiting for IT; same compose setup throughout |

## Open

- **AI as an actor**: AI inbox and labels as proposed in [ai.md](ai.md), or
  direct writes by default?
- **Notes integration**: sync notes as a Markdown folder (git) so people can
  write in Obsidian? Deep links `[[paper:doi]]`?
- **Word plugin**: when? LaTeX/Overleaf (BibTeX URL) and Markdown (CSL-JSON)
  first.
- **Tablet reading and offline**: web reader with touch/stylus support;
  desktop app (Tauri) later.
- **Who maintains the service** after the pilot: the group, the library or
  the computing centre?
- **Funding** if it grows: hosted version, support, grants.

## Other projects to learn from

- Zotero MCP servers (single-user): 54yyyu/zotero-mcp (`zotero-mcp-server`
  on PyPI), Zoteus, ZotPilot.
- Self-hosted libraries for groups: I, Librarian; community Zotero sync
  server forks.
- Self-hosted NotebookLM-style tools (with built-in chat): Open Notebook,
  SurfSense; also AnythingLLM, Khoj, PaperQA2.
- Paperless-ngx (office documents) and its MCP servers.
- Immich (architecture and operations, see [operations.md](operations.md)).

## Licences of things we might reuse (verify)

| What | Licence |
| --- | --- |
| Immich | AGPL-3.0 |
| Zotero client, translators, translation-server | AGPL-3.0 |
| CSL styles | CC BY-SA 3.0 |
| citeproc-js | CPAL/AGPL dual; citeproc-py as Python alternative |
| Names "Zotero", "Immich" and logos | Trademarks: not in our branding; "Import from Zotero" is fine |

Note borrowed code and its licence in `THIRD_PARTY.md`.
