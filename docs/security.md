# Security

What is checked, and how, so a change that weakens it fails a test. Who
may see and change what is described in [permissions.md](permissions.md).

## Who sees what

- **Every route, every person** (`server/tests/test_privacy.py`): a library
  is filled with private things (an own paper, a private note, private
  annotations, private tags and collections, a token's limits); then every
  `GET` route of the API, taken from the OpenAPI schema (a new route is
  covered by itself), is called as another member of the group and as an
  administrator, and none answers with any of it. Every other route is
  called with the private things' IDs and refused. Assistants (access
  tokens, the MCP server) likewise.
- **Groups and sharing** (`test_groups.py`, `test_permissions.py`): private
  libraries stay private; roles (reader, member, admin) and nested groups
  inherit downwards only; giving a paper to a group and taking it back;
  each action on papers, tags, collections and notes for each role.
- **Annotations** (`test_annotations.py`): one's own until shared, per
  paper; readers annotate too.
- **Syncing** (`test_sync.py`): `/api/changes` gives only what the person
  sees; what leaves their reach is reported as removed, with no content;
  the live stream says only that something changed.

## Signing in

- **Passwords** (`test_auth.py`): hashed with a slow hash, old hashes
  renewed at login; wrong password and unknown user answer alike; sessions
  end at logout and expire; the cookie is `Secure`, `HttpOnly`,
  `SameSite`; deactivated people cannot log in.
- **OIDC** (`test_oidc.py`): a login not started here is refused (state);
  the ID token's issuer, audience, expiry and nonce are checked (it comes
  straight from the provider's token endpoint over https, where OIDC lets
  its signature go unchecked); the provider's discovery must use https and
  name itself; accounts are matched (by username, never an
  administrator's: they link their login themselves) or made as configured.
- **Apps** (`test_oauth.py`): the app's login in the system's browser
  (PKCE, a one-time code to a loopback address only); assistants'
  connections (OAuth with registration rules, consent, revoking).
- **Access tokens and scopes** (`test_tokens.py`): every API route has a
  decided scope, or is closed to tokens (pinned in the test: a new route
  fails it until decided); a token limited to some libraries sees nothing
  else anywhere; tokens expire, are revoked, end with their person;
  administrators' tokens get no administration.

## The apps

- The library's website, a remote address, gets no access to the app
  (`app/src-tauri/capabilities/start.json`; the app's journeys check it).
- Logins are kept in the system's store of logins (Keychain, Credential
  Manager, GNOME Keyring, KWallet), else in a file of the person's alone;
  a copy for offline use opens only while logged in, and logging out
  deletes it (`docs/apps.md`, "Logins").

## Dependencies

- **Weekly** (`.github/workflows/audit.yml`, also by hand): known
  vulnerabilities in what paperus ships, with `pip-audit` (server, ML
  service), `npm audit` of the runtime packages (website, extension,
  client, app) and `cargo audit` (the app).
- **Build tools** (dev dependencies of the website and the client) are not
  shipped; their advisories are read when they are updated. On 2026-11-11:
  `js-yaml` and `deepmerge` in the API client generator, which only reads
  paperus's own schema.
- Dependency updates come as pull requests (Dependabot).

## Reporting a vulnerability

Privately, to the maintainers (the repository's Security tab, "Report a
vulnerability"), not in a public issue.
