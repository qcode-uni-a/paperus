# paperus

*Papers, for us.* A self-hosted research library for groups: think Zotero, but
with group sharing, search by meaning and integration with whatever AI
assistant you already use.

> Status: idea and design phase. Nothing is implemented yet. The pilot will run
> on a small server at the university.

## The idea

- **One library for the group**, on a university server with university login,
  plus private space for each member.
- **Search by meaning** across the full text of every paper, note and
  annotation, computed on the server with a small open model.
- **Bring your own AI**: no built-in chatbot and no AI vendor. Any assistant
  (Claude, ChatGPT, a university-hosted or local model) connects through an MCP
  server, sees only what the user may see, and cites the exact passage.
- **Sources first**: papers, lecture notes, meeting notes and their versions,
  with notes and annotations attached to them. Not a general notes app.
- **No lock-in**: full export of files, BibTeX/CSL-JSON, Markdown notes and
  annotations at any time.

## Documents

| Document | Contents |
| --- | --- |
| [Architecture](docs/architecture.md) | Components, stack, data model, scaling |
| [Ingestion](docs/ingestion.md) | Adding items, metadata, PDFs, browser extension, versions, other sources |
| [Search](docs/search.md) | Chunking, embeddings, hybrid search, deduplication across versions, pgvector |
| [AI integration](docs/ai.md) | MCP tools, permissions, the AI inbox, skill draft |
| [Operations](docs/operations.md) | Hosting at the university, data protection, lessons from Immich |
| [Decisions](docs/decisions.md) | Decisions made so far and open questions |
| [Pilot](docs/pilot.md) | Pilot plan and questions for testers |

## Development

Needs Docker, [uv](https://docs.astral.sh/uv/) and Node.js.

```sh
docker compose up -d                       # Postgres with pgvector on localhost
cd server
uv run alembic upgrade head
uv run paperus user create alice --admin   # asks for a password
uv run paperus serve --reload              # API on http://localhost:8000
uv run paperus worker                      # background jobs, in a second terminal

cd web
npm install
npm run dev                                # website on http://localhost:5173
npm run api                                # after API changes: regenerate the client
```

To try it from a phone on the same network: start the API with
`PAPERUS_COOKIE_SECURE=false` (plain HTTP outside localhost) and the website
with `npm run dev -- --host 0.0.0.0`, then open `http://<this PC's IP>:5173`.

`npm run build` writes the website to `web/build`, which `paperus serve`
serves on its own port as well. Checks: `uv run pytest`, `uvx pre-commit run --all-files`.

## Name

paperus: "papers for us", and it sounds like *papyrus*. `paperus` is free on
PyPI and npm (checked 2026-11-04).

## Licence

Apache-2.0, see [LICENSE](LICENSE).
