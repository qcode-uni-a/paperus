# Decisions and open questions

## Decided

| Topic | Decision | Why |
| --- | --- | --- |
| Name | paperus | "papers for us", sounds like papyrus; free on PyPI and npm. Domains not registered yet, on purpose. A small, unrelated GitHub project `Naridon-Inc/paperus` exists |
| Repository | In the university group's GitHub organization, repo `paperus` | Can be transferred later; redirects keep working |
| Relation to Zotero | Standalone, not built on Zotero; full Zotero import | Own data model for groups, versions, search; borrow ideas freely |
| Scope | Sources first (papers, lectures, meetings) and notes about them | Avoid becoming a Notion/Obsidian clone |
| AI | Bring your own AI via MCP; no LLM calls from the server | Vendor neutral, data stays on the server, cheaper |
| Server-side models | Embeddings, reranker, OCR only, open models, configurable | Needed for search; runs on CPU |
| Server language | Python (FastAPI); TypeScript for frontend and extension; Rust via PyO3 later if measured | The processing and model ecosystem is Python |
| Website | SvelteKit (static single-page app served by the server); API client generated with @hey-api/openapi-ts | One container to deploy; typed client from the OpenAPI schema. openapi-typescript was considered but is unmaintained |
| Database | Postgres + pgvector, queue in Postgres | One service to run; permission filters in SQL |
| PDF fetching | Server: open access only; browser: user's session; manual fallback | Licences, campus IP blocks |
| IDs | UUIDv7 for every record; SHA-256 only for blobs and chunks | Same bytes can be different files; IDs needed before an upload ends; hashes reveal content; stable links |
| Licence | Apache-2.0 for everything (server and integrations) | Allows every later use (hosted version, other universities, companies); can still move to AGPL later, not the other way round; patent grant over MIT |
| Owners | Every paper, tag and collection has one owner, a person or a group; sharing gives it to a group. Lists mix everything one can see. (Tried the same day: one library per item like Zotero, then items in several libraries; both felt too complicated) | As simple as possible to use; a paper exists once |
| Groups | Nested like GitLab: membership inherited downwards (a subgroup may raise a role, not lower it), nothing upwards. Roles reader, member, admin. Site admins create top-level groups; group admins create subgroups | Matches faculty → chair → project; well-known model |
| Notes | Own records (not items): Markdown in the database with an owner, linked to any number of papers (or none), in collections like papers; an edit history instead of versions; annotations later as their own step | Notes are the person's writing, not sources: no citation metadata, never cited; Zotero's child and standalone notes map onto them |
| Overviews | One mixed list of everything one can see; a small shared icon marks group papers and collections; no filter by owner needed | Work should feel like one library |
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

## Lessons from Zotero

Checked against Zotero's docs and source (2026-11-04).

- **Copied**: a change number per library stamped on every change, `since`
  queries, version checks on writes (412/428); a trash instead of deleting;
  separate manual and automatic tags (plus "suggested by AI").
- **Improved**: deduplication on add by any identifier (Zotero only finds
  duplicates afterwards); versions of a work (preprint, published, editions)
  instead of separate items; metadata as CSL-JSON, so no "Extra" catch-all
  field; storage not charged to a group's owner.
- **Still to copy**: merging duplicates keeps a "replaces" link so old IDs
  keep working, the losing item goes to the trash, tags and collections are
  united; batch writes with per-object results; `Backoff`/`Retry-After`
  headers for clients.
- **Avoid**: permissions only per library (users ask for per-collection
  permissions; plan for them early); no way to mark "not a duplicate";
  silent partial failures in identifier lookup.

## Licences of things we might reuse (verify)

| What | Licence |
| --- | --- |
| Immich | AGPL-3.0 |
| Zotero client, translators, translation-server | AGPL-3.0 |
| CSL styles | CC BY-SA 3.0 |
| citeproc-js | CPAL/AGPL dual; citeproc-py as Python alternative |
| Names "Zotero", "Immich" and logos | Trademarks: not in our branding; "Import from Zotero" is fine |

Note borrowed code and its licence in `THIRD_PARTY.md`.
