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
- **University login**: registration with the identity provider (SAML/
  Shibboleth or OIDC); list the attributes requested (name, email,
  affiliation). Group membership from the directory later.

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

## Lessons from Immich

- Separate model container, callable over HTTP, can run on a GPU machine or be
  turned off; models configurable in the admin UI and downloaded automatically.
- Vector extension changes happen (Immich moved from pgvecto.rs to
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
