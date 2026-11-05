<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo/paperus-logo-dark.svg">
    <img src="docs/logo/paperus-logo.svg" alt="paperus" height="64">
  </picture>
</h1>

*Papers, for us.* A self-hosted research library for groups: think Zotero, but
with group sharing, search by meaning and integration with whatever AI
assistant you already use.

> Status: early version (0.0.1) for a pilot in one group. It works, but every
> user sees every item and the data format may still change. See the
> [changelog](CHANGELOG.md) for what is there and what is missing.

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

## Installation

Needs a Linux machine with Docker and about 4 GB of RAM (the model for search
by meaning takes 2–3 GB).

1. Download [`deploy/compose.yaml`](deploy/compose.yaml) and
   [`deploy/example.env`](deploy/example.env) into a new folder; rename
   `example.env` to `.env`.
2. In `.env`, set `DB_PASSWORD` and `ML_TOKEN` (e.g. `openssl rand -hex 32`),
   and the folders for files, database and models.
3. Start: `docker compose up -d`. The first start downloads the model (about
   2.3 GB).
4. Create the first administrator:
   `docker compose exec server paperus user create admin --admin`
5. Put a reverse proxy with HTTPS in front of port 8000, on a (sub)domain of its
   own; examples for Caddy and nginx are in
   [operations](docs/operations.md#reverse-proxy).

Back up the files folder and the database folder together. To update, change
`PAPERUS_VERSION` or pull `release` again, then `docker compose up -d`.

## Documents

| Document | Contents |
| --- | --- |
| [Architecture](docs/architecture.md) | Components, stack, data model, scaling |
| [Ingestion](docs/ingestion.md) | Adding items, metadata, PDFs, browser extension, versions, other sources |
| [Search](docs/search.md) | Chunking, embeddings, hybrid search, deduplication across versions, pgvector |
| [Permissions](docs/permissions.md) | Who may do what with papers, tags, collections and groups |
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

cd ml                                      # machine learning service (search by meaning)
PAPERUS_ML_CACHE_PATH=../data/model-cache uv run paperus-ml
# or in a container, with the same model folder:
# docker compose --profile ml up -d

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

Apache-2.0, see [LICENSE](LICENSE). Bundled fonts and libraries keep their
own licences, see [THIRD_PARTY.md](THIRD_PARTY.md).
