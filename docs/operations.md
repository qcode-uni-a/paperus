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
- HTTPS is still needed: for the service worker (offline reading), and to
  keep passwords, access tokens and papers off the wire inside the campus
  network. A certificate for the machine's university hostname, e.g. via
  the university's ACME service. For a first try without one,
  `COOKIE_SECURE=false`: the website and the browser extension work over
  plain HTTP too.
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

The `ml` container computes the vectors for search by meaning, on the CPU
or on an NVIDIA GPU (below).
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

### On an NVIDIA GPU

Not sure whether it would help? The ML service sees the machine's NVIDIA
cards even from the CPU image (the kernel lists them in every container),
and an administrator's Getting started on the library page says what to
do: switch to the `-cuda` image, pass the GPU to its container, or update
the driver; or that it runs on the GPU, by name.

The image `paperus-ml:<version>-cuda` (e.g. `release-cuda`) is the same
service with ONNX Runtime's GPU build and CUDA (about 4 GB larger). On the
host: the NVIDIA driver (580 or newer, for CUDA 13; cards from the RTX 20xx
generation on) and the NVIDIA Container Toolkit, set up for Docker:

```sh
# Describe the GPUs for Docker (CDI), once and again after a driver update.
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
nvidia-ctk cdi list    # nvidia.com/gpu=all, nvidia.com/gpu=0, …
```

The toolkit comes from NVIDIA's package repository (see NVIDIA's
"Installing the NVIDIA Container Toolkit"); on Ubuntu or Debian:

```sh
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
```

With Secure Boot on, prefer a driver whose kernel modules come signed by
the distribution (on Ubuntu the `linux-modules-nvidia-<version>-…`
packages, listed by `ubuntu-drivers list`); a DKMS build needs a key
enrolled at the machine on the next boot.

The GPU by its CDI name (Docker 28 and newer), best in a
`compose.override.yaml` next to `compose.yaml`: Compose reads it on top,
and it survives replacing `compose.yaml` with a newer one
(`docker compose config` shows the merged result):

```yaml
services:
  ml:
    image: ghcr.io/qcode-uni-a/paperus-ml:${PAPERUS_VERSION:-release}-cuda
    devices:
      - nvidia.com/gpu=all
```

A check that containers reach the GPU: `docker run --rm --device
nvidia.com/gpu=all ubuntu nvidia-smi`.

The older form, `deploy.resources.reservations.devices` with
`driver: nvidia` (or `docker run --gpus all`), needs the NVIDIA runtime
registered in Docker (`sudo nvidia-ctk runtime configure --runtime=docker`
and a restart of Docker); with only CDI it fails with "could not select
device driver".

Administration → Settings → Machine learning then names the GPU; without a
reachable card the image runs on the CPU and logs why
(`PAPERUS_ML_DEVICE=cuda` refuses to start instead). Measured on an RTX
2080 SUPER (8 GB), against 24 CPU cores: arctic-embed-m-v2 188 passages/s
instead of 8, multilingual-e5-small 409 instead of 24, bge-m3 35 instead of
3. GPU memory per loaded model: 0.65 GB (e5-small), 1.6 GB (arctic), 3 GB
(bge-m3).

On the GPU the models run their fp16 files instead of the CPU's int8 ones;
the vectors differ (arctic: cosine 0.96–0.97), so they are stored under
another name (`arctic-embed-m-v2@fp16`) and a switch between CPU and GPU
re-embeds the library like a change of model (minutes on a GPU). All
addresses in `PAPERUS_ML_URLS` should run on the same kind of hardware.

### On another machine

The ML service can run elsewhere, for example on a workstation with an
NVIDIA GPU, while paperus stays on a small server: on the CPU, reading a
large library for search by meaning takes hours, on a GPU minutes. On that
machine, with Docker (and, for the GPU, the setup above), a `compose.yaml`
with the ML service only:

```yaml
services:
  ml:
    image: ghcr.io/qcode-uni-a/paperus-ml:release-cuda  # or release (CPU)
    devices:
      - nvidia.com/gpu=all
    environment:
      PAPERUS_ML_TOKEN: the-same-ML_TOKEN-as-paperus
    ports:
      - "3003:3003"
    volumes:
      - ./model-cache:/cache
    restart: unless-stopped
```

Then, in paperus' `.env`, its address, and `docker compose up -d`:

```sh
ML_URLS='["http://192.168.1.20:3003"]'
```

- The texts of the papers travel to it: keep it on a network you trust
  (the same LAN, a VPN), or put it behind a reverse proxy with HTTPS and
  use its `https://` address. The token keeps others from using it.
- paperus' own `ml` container then has nothing to do; take it out of
  `compose.yaml` to save its memory.
- Several addresses (`["http://a:3003", "http://b:3003"]`) are tried in
  order, so a second machine can stand in for the first; they should run
  on the same kind of hardware (see above: CPU and GPU vectors differ).
- Moving from a CPU to a GPU re-embeds the library once.
- Administration → Server shows whether the service answers; Settings →
  Machine learning, where it runs.

### OCR

Scanned pages (PDF pages without text) and images are read by the ML
service in the background (Administration → Settings → Machine learning →
Reading scans; on by default). About 3 s per page on a CPU, one file at a
time in its own job queue, so embedding is not held up; much faster on a
GPU. Administration → Jobs shows how many files wait. Files from before
0.0.11 without any text, and images, are read again by the upgrade;
scanned pages inside PDFs that had text already are found by "Read all
files again".

### Reranking

A reranker reads the question with each of the best 40 hits and puts the
best answers first (Administration → Settings → Machine learning →
Reranking). On our test questions (docs/search.md) bge-reranker-v2-m3 put
the right paper first 89 times in 100 instead of 66, and in the top five 98
times. A search then takes about 0.6 s on an RTX 2080 SUPER instead of
0.15 s; on a CPU many seconds, so "Automatic" (the default) reranks only
when the ML service runs on a GPU. The reranker needs about 1.2 GB of GPU
memory; the ML service gives back what a batch needed after each run, so
models and other programs share the card. If reranking fails or takes
longer than 15 s, results come in the usual order.

## Logs

The server and the worker write their log to the container's output
(`docker compose logs server worker`) and, for the last two weeks, into the
database, where administrators read it under Administration → Logs: by
level, by source and by words. paperus's own messages are kept at the level
set under Settings → Logging, other libraries' from warnings up. People's
browser extensions add their warnings and errors there too (a paper saved
without its PDF and why, with the page's address and who it was), so a
publisher that refuses PDFs shows up without asking around. The night's
tidy-up deletes entries older than two weeks, and beyond the newest
100,000.

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
weekly, at a chosen hour, keeping the newest N; by default daily at 03:00
UTC, the database only, the newest 7), into `BACKUP_LOCATION`;
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

**People's exports** (Settings → Export, see [export](export.md)) are
written to `exports/` beside the stored files (`/data/files/exports` in
the container; `PAPERUS_EXPORT_PATH` to change it) and deleted after a
day. They are not part of the file store and not backed up; a large
library's export needs about its size in free space there for that day.

## Releases

Pushing a tag `vX.Y.Z` (matching the versions in `server/pyproject.toml`,
`ml/pyproject.toml`, `web/package.json`, `client/package.json` and
`extension/package.json`) runs `.github/workflows/release.yml`: the tests,
then the container images on ghcr.io (tags `vX.Y.Z`, `X.Y.Z` and
`release`), then a GitHub release with the notes from `CHANGELOG.md` and the
browser extension's zips (for Chrome and Firefox).

The packages are published only once their setup is done and switched on
with repository variables (Settings → Secrets and variables → Actions →
Variables):

- PyPI (`paperus`, `paperus-ml`): a trusted publisher on pypi.org for each
  (owner `qcode-uni-a`, repository `paperus`, workflow `release.yml`,
  environment `pypi` for `paperus` and `pypi-ml` for `paperus-ml`), then
  `PUBLISH_PYPI` = `true`.
- npm (`paperus`): trusted publishing, no token (set up 2026-11-08 in the
  package's settings on npmjs.com: GitHub Actions, owner `qcode-uni-a`,
  repository `paperus`, workflow `release.yml`, environment `npm`; allowed
  to `npm publish` directly; for people two-factor authentication without
  bypass tokens), and `PUBLISH_NPM` = `true`.

- Firefox add-on (addons.mozilla.org, listed since 0.0.10): an API key
  from <https://addons.mozilla.org/developers/addon/api/key/> as the
  secrets `AMO_JWT_ISSUER` and `AMO_JWT_SECRET` (in an environment
  `firefox`), then `PUBLISH_FIREFOX` = `true`. A release hands in the
  new version with its source (`extension/amo-metadata.json`: the notes for
  the reviewers); it is listed once Mozilla approves it.

- Chrome extension (Chrome Web Store, handed in by hand for 0.0.10): in
  Google Cloud, a project with the "Chrome Web Store API" enabled and a
  service account (no roles) with a JSON key; the service account's email
  added in the store's Developer Dashboard under Account. Then the key as
  the secret `CHROME_SERVICE_ACCOUNT_KEY` (environment `chrome`), the
  variables `CHROME_PUBLISHER_ID` (Dashboard → Account) and
  `CHROME_ITEM_ID` (the extension's ID, in the item's address), and
  `PUBLISH_CHROME` = `true`. A release uploads the new version and hands
  it in for review. Actions → "Check store access" tests both stores' keys
  without uploading anything.
- Both stores only get a new version when the extension changed since the
  previous release tag: the release builds both and compares what ships,
  apart from the version (`.github/scripts/extension-changed.sh`). The
  GitHub release always has the zips.

After the first release, make the two packages on ghcr.io public (package
settings), so `docker compose pull` works without logging in.

## Database maintenance

Postgres's autovacuum keeps tables and statistics in shape; nothing else
needs scheduling so far (checked 2026-11-05). The worker tidies what grows
without end:

- **Every hour**: jobs whose worker stopped in the middle (killed, crashed)
  are retried; otherwise they would stay "doing" for ever.
- **Every night** at the night jobs' hour: finished background jobs older
  than a week (failed ones after a month) and expired login sessions are
  deleted. Without this, the job table grows by about 1,500 rows and 4,500
  events a day.

Search by meaning has no vector index yet (exact search; fine at pilot size,
see issue #37).

## Checks and updates

- **CI** (`.github/workflows/ci.yml`) on every push and pull request: the
  pre-commit hooks on all files, then the server, the ML service, the
  website, the TypeScript client and both container images. And the
  update test (`deploy/update-test/run.sh`): an installation from
  `deploy/compose.yaml` on the last release, filled with two people, a
  group, papers, a PDF, tags, a collection, notes and a highlight, updated
  to the new server image with `docker compose up -d`; then everything must
  still be there and each person see what they did before. Locally: build
  the image as `ghcr.io/qcode-uni-a/paperus-server:ci` first.
- **Dependabot** (`.github/dependabot.yml`) opens update pull requests every
  Monday: Python (uv), npm, the base images (python, node, uv, Postgres),
  GitHub Actions and the pre-commit hooks. Minor and patch updates come
  grouped; major ones one by one. New releases wait a week first. Security
  updates come at once. Merge when CI is green; a major update may need
  changes (read its notes).

## Outside services

What the server sends where (for the data protection description and for
firewalls). Each request names paperus and the contact email from
Administration → Server (`User-Agent: paperus/<version> (mailto:…)`), as
these services ask; nothing about people or their notes is sent.

| Service | What it gets | When | Off with |
| --- | --- | --- | --- |
| doi.org (Crossref, DataCite) | A DOI | Adding a paper by DOI, a DOI found in a file, published versions found | (needed for details) |
| arXiv: `export.arxiv.org` | arXiv IDs, 50 at a time | Looking for preprints' published versions (hourly, each paper monthly) | Server → Published versions |
| arXiv: `arxiv.org/pdf` | An arXiv ID | Downloading an open copy (Missing, Download again, open-access copies) | (on request) / Server → Open-access copies |
| OpenAlex: `api.openalex.org` | A DOI or arXiv ID | Published versions; a paper's arXiv version and the journal's open copy | Server → Published versions / Open-access copies |
| Unpaywall: `api.unpaywall.org` | A DOI | Open copies, only with a contact email | No contact email |
| Publishers, repositories | A PDF address OpenAlex or Unpaywall gave | Downloading an open copy | as above |
| Hugging Face | A model name | The ML service's first use of a model | Model cache filled once |
| The OIDC provider | The login | OIDC login | Server → OIDC |

The browser extension talks only to the person's paperus and, on their
click, to the page they are on or (Manage → Missing) the publishers' pages
of the papers they chose (see `extension/PRIVACY.md`).

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
- The server never fetches from publishers behind a login (campus IP
  range, licences): only open copies, on request or by itself with
  Server → Open-access copies on. Copies behind a login come through the
  person's own browser (the extension), only on their click.
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
