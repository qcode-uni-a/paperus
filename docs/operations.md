# Operations

## Stages

0. **Local**: on the developer's machine, `localhost` only, for building and
   trying things out. No other users, no HTTPS needed (`localhost` counts as
   a secure context for the service worker and the extension).
1. **Test server on the university VPN** (below).
2. **Pilot hosting at the university** (below).

## Stage 1: test server on the university VPN

Before the computing centre hosts it, run paperus on an always-on machine of
the group at the university, reachable only through the university VPN.

- Same `docker compose up` as later: a test of the self-hosting setup.
- Login: username and password, accounts created by an admin. Keep auth
  behind one layer so university login (OIDC/SAML) can replace it later
  without migrating users (link existing accounts by email).
- AI: only clients on the user's own machine (Claude Code, Claude Desktop,
  Cursor, local models) through the stdio bridge/CLI with a personal API
  token. Hosted connectors (Claude.ai, ChatGPT) cannot reach a VPN-only
  server; they come with the next stage.
- HTTPS is still needed (browser extension, service worker): a certificate
  for the machine's university hostname, e.g. via the university's ACME
  service.
- Backups and a tested restore from the start: testers' notes are real data.
- Testers know it is a test server; data moves to the pilot server.

## Stage 2: pilot hosting at the university

Ask the computing centre for:

- **A VM**, not a physical box, ideally with their backups and monitoring.
  Pilot size: 4–8 vCPUs, 16–32 GB RAM, a few hundred GB to 1 TB storage
  (backed up; S3-compatible object storage if offered). No GPU needed at first.
- **Network**: campus/VPN only is easiest. Remote MCP connectors (Claude,
  ChatGPT) need the server reachable from the internet over HTTPS: clarify
  early with IT security.
- **DNS name and TLS certificate** (ACME from the university or Let's Encrypt).
- **University login (OIDC)**: registration with the identity provider as an
  OpenID Connect client (confidential, authorization code flow with PKCE;
  scopes `openid profile email`). Give them the redirect address shown in
  Administration → Settings → Authentication
  (`https://<host>/api/auth/oidc/callback`); enter the issuer, client ID and
  secret there (or the secret as `PAPERUS_OIDC_CLIENT_SECRET`). The client
  authenticates with `client_secret_post`. SAML-only providers need a bridge
  (Keycloak, SATOSA). Group membership from the directory later.
- **Administrators keep a password**: with password login off, only
  administrators may still use one, their way in if the identity provider
  fails. Link their accounts to the OIDC login (on first setup, or
  "Link my account" under Authentication).

Agree in writing who patches the OS and who updates the application. Automate
updates (container images + script or Ansible), set up backups and test a
restore.

## Reverse proxy

paperus serves the website, the API and file downloads on **one port**
(8000); the ML service and the database are only reachable inside the
Docker network. Put a reverse proxy with HTTPS in front of that port, on a
**domain or subdomain of its own** (serving under a path such as
`example.org/paperus/` is not supported).

- The proxy's `X-Forwarded-For`/`-Proto` headers are trusted from this
  machine and private networks (`PAPERUS_TRUSTED_PROXIES`, addresses or
  CIDR ranges); narrow it if the server port is reachable from elsewhere.
- Uploads can be large (up to `PAPERUS_MAX_UPLOAD_BYTES`, 512 MB by
  default): raise the proxy's body size limit and timeouts.
- Downloads use range requests (PDF.js loads large PDFs in parts); proxies
  pass them through by default.

Caddy (gets and renews certificates by itself):

```
paperus.example.org {
	reverse_proxy localhost:8000
}
```

nginx (certificates set up separately, e.g. with certbot):

```nginx
server {
    listen 443 ssl;
    server_name paperus.example.org;
    # ssl_certificate …; ssl_certificate_key …;

    client_max_body_size 512m;   # nginx allows 1 MB by default
    proxy_request_buffering off; # stream uploads instead of buffering them

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
    }
}
```

Tested with Caddy in front of the container images: HTTPS, login with the
Secure session cookie, uploads, downloads with range requests.

## ML service (search by meaning)

The `ml` container computes the vectors for search by meaning on the CPU.
Its settings are made under Administration → Settings → Machine learning
and sent to it by the server (at once, when the server starts, and every
five minutes, so a restarted ML service gets them back):

- **The model**, chosen by published scores and a speed test on this
  server; the ML service keeps it loaded.
- **CPU cores** it may use (default: all it sees). Lower it to keep cores
  free for the database and the server on the same machine. Docker's
  `cpus:` limit alone is not enough: inside a container the host's cores
  are still seen, and too many threads slow it down.
- **One batch at a time per model**: each batch uses all of its cores;
  simultaneous requests (several uploads, a search) take turns batch by
  batch, so a search waits for one batch at most.

## Monitoring (Prometheus)

The server and the ML service can serve Prometheus metrics, each on a port
of its own, so they are not reachable through the public address: set
`PAPERUS_METRICS_PORT` (e.g. 9464) for the server and
`PAPERUS_ML_METRICS_PORT` (e.g. 9465) for the ML service (both are
commented out in `compose.yaml`). Prometheus scrapes them inside the
Docker network, e.g. with a `prometheus` service in the same compose
project:

```yaml
scrape_configs:
  - job_name: paperus
    static_configs:
      - targets: ["server:9464", "ml:9465"]
```

Server (`paperus_…`):

- `http_requests_total`, `http_request_duration_seconds` by method, route
  pattern and status;
- `searches_total` by mode, `search_duration_seconds`;
- `ml_calls_total` by outcome (ok, loading, rejected, unavailable),
  `ml_call_duration_seconds`;
- the library, read at each scrape: `items`, `items_in_trash`, `files`,
  `files_pending`, `notes`, `users`, `groups`, `storage_bytes`, `chunks`,
  `embedded_chunks{model}`, `imports_running`, `jobs{queue,status}`,
  `last_backup_timestamp_seconds`;
- and the usual process metrics (memory, CPU, open files).

ML service (`paperus_ml_…`): `requests_total{model,kind,outcome}`,
`texts_total`, `batch_duration_seconds{model}`, `model_loaded{model}`
(1 loaded, 0.5 loading).

Worth an alert: `files_pending` or `jobs{status="failed"}` growing,
`ml_calls_total{outcome="unavailable"}` rising, the last backup older than
its schedule.

## Backups

Administration → Backups writes backups now or on a schedule (daily or
weekly, at a chosen hour, keeping the newest N), into `BACKUP_LOCATION`;
put that on another disk or a network share. Each backup is a folder with
every table (compressed, with checksums) and a manifest naming the paperus
version and database migration. With "files", the files are copied too:
into one pool shared by all backups, so each backup copies only new files.
The model cache needs no backup (it is downloaded again).

From the command line (in the container, or with the same settings):

```sh
docker compose exec server paperus backup create          # with files
docker compose exec server paperus backup create --no-files
docker compose exec server paperus backup list
```

**On a new server** (or after losing the old one): copy the backup folder
(the backup itself and the `files` folder next to it) into `BACKUP_LOCATION`,
start paperus and choose "Restore from a backup" on the first page. That
page only appears while paperus has no users, so it needs no downtime.

**Files when restoring.** Files are stored by their SHA-256, so a file
already in the storage is the very same file: nothing is ever overwritten.
Before restoring, paperus checks where each file the backup's papers use
comes from: already in the storage (e.g. only the server died), copied back
from the backup, or missing from both. Missing files (a database-only
backup with an empty storage, or an incomplete one) get a warning naming
the papers that would open without their file. Files in the storage that
the backup does not know (added after it) stay on disk.

**Replacing** a running installation's database needs it stopped first:

```sh
docker compose stop server worker
docker compose run --rm server paperus backup restore 2026-11-05T03-00-00Z --replace
docker compose up -d
```

Without `--replace` it restores only into an empty database (e.g. a new
installation). Restoring checks every table's checksum, creates the schema
at the backup's migration, loads the data, migrates to the running version
and copies back files that are missing. A backup from a newer paperus is
refused: update paperus first. Search data (passages, vectors) is in the
backup, so search works right away.

## Releases

Pushing a tag `vX.Y.Z` (matching the versions in `server/pyproject.toml`,
`ml/pyproject.toml`, `web/package.json` and `client/package.json`) runs
`.github/workflows/release.yml`: the tests, then the container images on
ghcr.io (tags `vX.Y.Z`, `X.Y.Z` and `release`), then a GitHub release with
the notes from `CHANGELOG.md`.

The packages are published only once their setup is done and switched on
with repository variables (Settings → Secrets and variables → Actions →
Variables):

- PyPI (`paperus`, `paperus-ml`): a trusted publisher on pypi.org for each
  (owner `qcode-uni-a`, repository `paperus`, workflow `release.yml`,
  environment `pypi`), then `PUBLISH_PYPI` = `true`.
- npm (`paperus`): a secret `NPM_TOKEN` for the first release (trusted
  publishing on npmjs.com afterwards), then `PUBLISH_NPM` = `true`.

After the first release, make the two packages on ghcr.io public (package
settings), so `docker compose pull` works without logging in.

## Data protection and licences

- Involve the data protection officer early: accounts, notes, usage logs are
  personal data. Short description of the processing plus a contact person.
- Text sent to the user's AI through MCP leaves the university: the user's
  choice, but documented; per-group restriction to local or university models.
- Ask the library whether licensed PDFs may be shared within a group;
  per-group setting to share metadata and annotations only.
- The pilot assumes sharing licensed PDFs within a group is allowed. When an
  admin adds users to a group, warn that the group's licences must permit
  this.
- Never fetch from publishers automatically (campus IP range, licences).
- Meeting notes: participants-only by default, retention setting.

## Self-hosting principles

- Minimal dependencies: Postgres, object storage (or filesystem), the app
  container, the model container. One `docker compose up`.
- Settings in the web UI, not config files (login, storage, models, jobs).
- File storage: `PAPERUS_STORAGE_BACKEND=filesystem` (default) for any
  mounted path (local disk, NFS, SMB; temporary files on the same mount, so
  renames stay atomic) or `s3` for S3-compatible storage (AWS, MinIO, Ceph,
  a university service) with `PAPERUS_S3_BUCKET`, `PAPERUS_S3_ENDPOINT_URL`,
  `PAPERUS_S3_PREFIX` and the usual AWS credentials. Contents are stored
  once per SHA-256 either way, so moving between backends is a copy.
- One-command backup and restore; full export in open formats.
- Helm chart later for university IT.

## Lessons from similar projects

- Separate model container, callable over HTTP, can run on a GPU machine or be
  turned off; models configurable in the admin UI and downloaded automatically.
- Vector extension changes happen (others moved from pgvecto.rs to
  VectorChord): hide the extension behind our own layer.
- Job queue with an admin page: status and concurrency per job type, "process
  missing" and "re-run all" buttons (metadata, parsing, embeddings, OA checks,
  related papers).
- One `docker-compose.yml` + `.env`, clear upgrade notes and breaking-change
  warnings, clear backup instructions (database + upload folder).
- External libraries (index a folder read-only), checksum deduplication,
  shared albums/links, mobile background upload, bulk-upload CLI: all map to
  paperus features.
- Honest maturity warnings early on; export working from day one.
