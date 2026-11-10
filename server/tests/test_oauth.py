"""OAuth for connected apps: an AI assistant registers, the person allows
it, and it uses the MCP server with short-lived tokens."""

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from paperus import oauth
from paperus.models import OAuthCode, OAuthGrant, User
from tests.people import Person
from tests.test_mcp import Assistant, ToolFailed

REDIRECT = "https://claude.ai/api/mcp/auth_callback"


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def register(client: TestClient, *uris: str) -> str:
    response = client.post(
        "/api/oauth/register",
        json={"client_name": "Claude", "redirect_uris": list(uris or [REDIRECT])},
    )
    assert response.status_code == 201, response.text
    client_id: str = response.json()["client_id"]
    return client_id


def consent(
    person: Person,
    client_id: str,
    challenge: str,
    *,
    allow: bool = True,
    scopes: list[str] | None = None,
    scope: str | None = None,
    redirect_uri: str = REDIRECT,
) -> dict[str, list[str]]:
    """The person allows (or not); the parameters the app gets back."""
    request = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": scope,
        "state": "xyz",
    }
    shown = person.post("/api/oauth/consent/check", json=request)
    assert shown.status_code == 200, shown.text
    body = {
        **request,
        "allow": allow,
        "scopes": scopes if scopes is not None else shown.json()["scopes"],
    }
    response = person.post("/api/oauth/consent", json=body)
    assert response.status_code == 200, response.text
    target = urlsplit(response.json()["redirect"])
    assert f"{target.scheme}://{target.netloc}{target.path}" == redirect_uri
    return parse_qs(target.query)


def exchange(client: TestClient, **form: str) -> Any:  # noqa: ANN401 (JSON)
    return client.post("/api/oauth/token", data=form)


def test_connecting_an_assistant(client: TestClient, db: Session) -> None:
    # The MCP server says where to start.
    response = client.post("/mcp", json={})
    assert response.status_code == 401
    server = client.get("/.well-known/oauth-authorization-server").json()
    base = server["issuer"]
    metadata = f"{base}/.well-known/oauth-protected-resource/mcp"
    assert response.headers["WWW-Authenticate"] == (
        f'Bearer resource_metadata="{metadata}"'
    )
    resource = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert resource["resource"] == f"{base}/mcp"
    assert resource["authorization_servers"] == [base]
    assert server["code_challenge_methods_supported"] == ["S256"]
    assert server["authorization_endpoint"] == f"{base}/oauth/authorize"

    ada = Person(client, db, "ada")
    ada.add("Floquet qubits")
    client_id = register(client)
    verifier, challenge = pkce()
    shown = ada.post(
        "/api/oauth/consent/check",
        json={
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "search papers.read papers.write unknown",
        },
    ).json()
    assert shown == {
        "client_name": "Claude",
        "redirect_host": "claude.ai",
        "scopes": ["papers.read", "papers.write", "search"],
        "username": "ada",
    }
    # Ada allows reading only.
    back = consent(
        ada,
        client_id,
        challenge,
        scope="search papers.read papers.write",
        scopes=["search", "papers.read"],
    )
    assert back["state"] == ["xyz"]
    assert back["iss"] == [base]
    [code] = back["code"]

    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT,
        "client_id": client_id,
    }
    wrong = exchange(client, **form, code_verifier=pkce()[0])
    assert wrong.status_code == 400 and wrong.json()["error"] == "invalid_grant"
    # The code was used up by the failed try (a guess costs the real one).
    again = exchange(client, **form, code_verifier=verifier)
    assert again.status_code == 400

    back = consent(ada, client_id, challenge, scopes=["search", "papers.read"])
    form["code"] = back["code"][0]
    tokens = exchange(client, **form, code_verifier=verifier)
    assert tokens.status_code == 200, tokens.text
    issued = tokens.json()
    assert issued["token_type"] == "Bearer" and issued["expires_in"] == 3600
    assert issued["scope"] == "papers.read search"
    assert tokens.headers["Cache-Control"] == "no-store"

    ai = Assistant(client, issued["access_token"])
    papers = ai.call("list_documents")["papers"]
    assert [p["title"] for p in papers] == ["Floquet qubits"]
    with pytest.raises(ToolFailed, match="lacks the scope"):
        ai.call("add_tags", paper_ids=[papers[0]["paper_id"]], tags=["x"])

    # Listed as a connected app, not as one of Ada's tokens.
    assert ada.get("/api/me/tokens").json() == []
    [app] = ada.get("/api/me/connected-apps").json()
    assert app["name"] == "Claude" and app["scopes"] == ["papers.read", "search"]

    # Refreshing gives new tokens; the old refresh token is used up.
    refresh = {"grant_type": "refresh_token", "client_id": client_id}
    renewed = exchange(client, **refresh, refresh_token=issued["refresh_token"])
    assert renewed.status_code == 200, renewed.text
    old = exchange(client, **refresh, refresh_token=issued["refresh_token"])
    assert old.status_code == 400
    other_client = register(client)
    stolen = exchange(
        client,
        grant_type="refresh_token",
        client_id=other_client,
        refresh_token=renewed.json()["refresh_token"],
    )
    assert stolen.status_code == 400

    # Disconnecting ends it at once.
    assert ada.delete(f"/api/me/connected-apps/{app['id']}").status_code == 204
    with pytest.raises(ToolFailed, match="invalid, expired or revoked"):
        Assistant(client, renewed.json()["access_token"]).call("list_documents")
    gone = exchange(client, **refresh, refresh_token=renewed.json()["refresh_token"])
    assert gone.status_code == 400


def test_refusing_and_wrong_requests(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    client_id = register(client)
    verifier, challenge = pkce()
    back = consent(ada, client_id, challenge, allow=False)
    assert back["error"] == ["access_denied"] and "code" not in back

    # Nothing asked for: reading only is offered.
    request = {
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    shown = ada.post("/api/oauth/consent/check", json=request).json()
    assert shown["scopes"] == ["files.read", "papers.read", "search"]
    # More than asked is not given.
    back = consent(ada, client_id, challenge, scopes=["papers.write"])
    assert back["error"] == ["access_denied"]

    for wrong in (
        {"redirect_uri": "https://evil.example/callback"},
        {"client_id": "unknown"},
        {"code_challenge_method": "plain"},
        {"code_challenge": "short"},
    ):
        response = ada.post("/api/oauth/consent/check", json={**request, **wrong})
        assert response.status_code == 400, wrong
    # Not with a token: only the person, logged in.
    raw = ada.post(
        "/api/me/tokens", json={"name": "script", "scopes": ["papers.read"]}
    ).json()["token"]
    response = client.post(
        "/api/oauth/consent/check",
        json=request,
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert response.status_code == 403

    # Expired codes are refused.
    back = consent(ada, client_id, challenge)
    db.execute(
        update(OAuthCode).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db.commit()
    response = exchange(
        client,
        grant_type="authorization_code",
        code=back["code"][0],
        redirect_uri=REDIRECT,
        client_id=client_id,
        code_verifier=verifier,
    )
    assert response.json()["error"] == "invalid_grant"


def test_registration_rules(client: TestClient, db: Session) -> None:
    for uri in (
        "http://claude.ai/callback",
        "javascript:alert(1)",
        "https://claude.ai/cb#fragment",
        "data:text/html,hi",
    ):
        response = client.post("/api/oauth/register", json={"redirect_uris": [uri]})
        assert response.status_code == 400, uri
    # Desktop apps: back to this computer, on any port.
    ada = Person(client, db, "ada")
    client_id = register(client, "http://127.0.0.1/callback", "cursor://oauth/cb")
    _, challenge = pkce()
    back = consent(
        ada, client_id, challenge, redirect_uri="http://127.0.0.1:53682/callback"
    )
    assert "code" in back
    back = consent(ada, client_id, challenge, redirect_uri="cursor://oauth/cb")
    assert "code" in back
    # Browsers may read the metadata and get tokens from elsewhere.
    response = client.options(
        "/api/oauth/token", headers={"Origin": "http://localhost:6274"}
    )
    assert response.headers["Access-Control-Allow-Origin"] == "*"


def test_revoking_and_deactivated_people(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    client_id = register(client)
    verifier, challenge = pkce()
    back = consent(ada, client_id, challenge)
    issued = exchange(
        client,
        grant_type="authorization_code",
        code=back["code"][0],
        redirect_uri=REDIRECT,
        client_id=client_id,
        code_verifier=verifier,
    ).json()
    # The app disconnects itself.
    response = client.post("/api/oauth/revoke", data={"token": issued["refresh_token"]})
    assert response.status_code == 200
    assert ada.get("/api/me/connected-apps").json() == []

    back = consent(ada, client_id, challenge)
    issued = exchange(
        client,
        grant_type="authorization_code",
        code=back["code"][0],
        redirect_uri=REDIRECT,
        client_id=client_id,
        code_verifier=verifier,
    ).json()
    response = root.patch(f"/api/admin/users/{ada.id}", json={"active": False})
    assert response.status_code == 200, response.text
    refreshed = exchange(
        client,
        grant_type="refresh_token",
        client_id=client_id,
        refresh_token=issued["refresh_token"],
    )
    assert refreshed.status_code == 400


def test_token_requests_that_go_wrong(client: TestClient, db: Session) -> None:
    assert client.get("/.well-known/oauth-protected-resource").json() == (
        client.get("/.well-known/oauth-protected-resource/mcp").json()
    )
    ada = Person(client, db, "ada")
    client_id = register(client)
    verifier, challenge = pkce()

    def code() -> dict[str, str]:
        return {
            "grant_type": "authorization_code",
            "code": consent(ada, client_id, challenge)["code"][0],
            "redirect_uri": REDIRECT,
            "code_verifier": verifier,
        }

    def error(response: Any) -> tuple[int, str]:  # noqa: ANN401 (a response)
        return response.status_code, response.json()["error"]

    assert error(exchange(client, **code())) == (401, "invalid_client")
    unknown = exchange(client, **code(), client_id="unknown")
    assert error(unknown) == (401, "invalid_client")
    for wrong in ("Basic abc", "Basic /w==", "Bearer abc"):
        response = client.post(
            "/api/oauth/token", data=code(), headers={"Authorization": wrong}
        )
        assert error(response) == (401, "invalid_client"), wrong
    for form in (
        {"grant_type": "authorization_code", "code": "c"},
        {"grant_type": "refresh_token"},
    ):
        response = exchange(client, **form, client_id=client_id)
        assert error(response) == (400, "invalid_request")
    password = exchange(client, grant_type="password", client_id=client_id)
    assert error(password) == (400, "unsupported_grant_type")
    elsewhere = {**code(), "redirect_uri": "https://claude.ai/other"}
    assert error(exchange(client, **elsewhere, client_id=client_id)) == (
        400,
        "invalid_grant",
    )
    short = {**code(), "code_verifier": "short"}
    assert error(exchange(client, **short, client_id=client_id))[1] == "invalid_grant"

    # The client_id by HTTP Basic, as some apps send it.
    basic = base64.b64encode(f"{client_id}:".encode()).decode()
    issued = client.post(
        "/api/oauth/token", data=code(), headers={"Authorization": f"Basic {basic}"}
    )
    assert issued.status_code == 200, issued.text

    # Unused too long: the connection ends.
    db.execute(
        update(OAuthGrant).values(
            refresh_expires_at=datetime.now(UTC) - timedelta(seconds=1)
        )
    )
    db.commit()
    expired = exchange(
        client,
        grant_type="refresh_token",
        client_id=client_id,
        refresh_token=issued.json()["refresh_token"],
    )
    assert expired.json()["error_description"] == "The connection has expired."
    assert ada.get("/api/me/connected-apps").json() == []


def test_requests_and_registrations_refused(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    for uris in ([], ["http://[::1/callback"], ["https://" + "a" * 2000]):
        response = client.post("/api/oauth/register", json={"redirect_uris": uris})
        assert response.json()["error"] == "invalid_redirect_uri", uris
    client_id = register(client)
    _, challenge = pkce()
    implicit = ada.post(
        "/api/oauth/consent/check",
        json={
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "response_type": "token",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert implicit.status_code == 400
    assert implicit.json()["detail"] == "Only response_type=code."
    # A code for someone deactivated before the app used it.
    root = Person(client, db, "root", admin=True)
    verifier, challenge = pkce()
    back = consent(ada, client_id, challenge)
    root.patch(f"/api/admin/users/{ada.id}", json={"active": False})
    response = exchange(
        client,
        grant_type="authorization_code",
        code=back["code"][0],
        redirect_uri=REDIRECT,
        client_id=client_id,
        code_verifier=verifier,
    )
    assert response.json()["error_description"] == "The account is not active."


def test_revoking_with_the_access_token(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    client_id = register(client)
    verifier, challenge = pkce()
    issued = exchange(
        client,
        grant_type="authorization_code",
        code=consent(ada, client_id, challenge)["code"][0],
        redirect_uri=REDIRECT,
        client_id=client_id,
        code_verifier=verifier,
    ).json()
    # Unknown tokens and one's own tokens are no error, and change nothing.
    own = ada.post(
        "/api/me/tokens", json={"name": "script", "scopes": ["papers.read"]}
    ).json()["token"]
    for token in ("whatever", "paperusr_unknown", own):
        assert client.post("/api/oauth/revoke", data={"token": token}).is_success
    assert len(ada.get("/api/me/connected-apps").json()) == 1
    assert len(ada.get("/api/me/tokens").json()) == 1
    response = client.post("/api/oauth/revoke", data={"token": issued["access_token"]})
    assert response.status_code == 200
    assert ada.get("/api/me/connected-apps").json() == []
    with pytest.raises(ToolFailed, match="invalid, expired or revoked"):
        Assistant(client, issued["access_token"]).call("list_documents")


APP = "http://127.0.0.1/done"
"""The paperus app registers its loopback address without a port."""


def app_code(
    person: Person, client_id: str, challenge: str, *, allow: bool = True
) -> dict[str, list[str]]:
    """The person logs the app in (or not); what the app gets back."""
    request = {
        "client_id": client_id,
        "redirect_uri": "http://127.0.0.1:53124/done",
        "code_challenge": challenge,
        "state": "s1",
    }
    shown = person.post("/api/oauth/app-login/check", json=request)
    assert shown.status_code == 200, shown.text
    assert shown.json() == {"client_name": "Claude", "username": "ada"}
    response = person.post("/api/oauth/app-login", json={**request, "allow": allow})
    assert response.status_code == 200, response.text
    target = urlsplit(response.json()["redirect"])
    assert (target.netloc, target.path) == ("127.0.0.1:53124", "/done")
    query = parse_qs(target.query)
    assert query["state"] == ["s1"]
    return query


def app_session(client: TestClient, client_id: str, code: str, verifier: str) -> Any:  # noqa: ANN401 (JSON)
    return client.post(
        "/api/oauth/app-session",
        json={
            "client_id": client_id,
            "code": code,
            "redirect_uri": "http://127.0.0.1:53124/done",
            "code_verifier": verifier,
        },
    )


def test_logging_in_the_app(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    client_id = register(client, APP)
    verifier, challenge = pkce()

    # Logged in on the website only (the person's login cookie gone).
    client.cookies.clear()
    request = {"client_id": client_id, "redirect_uri": APP, "code_challenge": challenge}
    assert client.post("/api/oauth/app-login/check", json=request).status_code == 401

    code = app_code(ada, client_id, challenge)["code"][0]
    response = app_session(client, client_id, code, verifier)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    session = response.json()
    assert session["max_age"] == 30 * 24 * 3600
    # The website's own login, as the app sets it as the cookie.
    me = client.get(
        "/api/auth/me", headers={"Cookie": f"paperus_session={session['token']}"}
    )
    assert me.json()["username"] == "ada"
    # A session, not a connected app; and the code is used up.
    assert ada.get("/api/me/connected-apps").json() == []
    again = app_session(client, client_id, code, verifier)
    assert again.json()["error"] == "invalid_grant"

    # Refused: no code then.
    assert "code" not in app_code(ada, client_id, challenge, allow=False)
    assert app_code(ada, client_id, challenge, allow=False)["error"] == [
        "access_denied"
    ]


def test_app_logins_that_go_wrong(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    client_id = register(client, APP)
    verifier, challenge = pkce()

    # The app's code gives no tokens, and a wrong verifier no session.
    code = app_code(ada, client_id, challenge)["code"][0]
    tokens = exchange(
        client,
        grant_type="authorization_code",
        client_id=client_id,
        code=code,
        redirect_uri="http://127.0.0.1:53124/done",
        code_verifier=verifier,
    )
    assert tokens.status_code == 400
    assert "paperus app" in tokens.json()["error_description"]
    code = app_code(ada, client_id, challenge)["code"][0]
    wrong = app_session(client, client_id, code, pkce()[0])
    assert wrong.status_code == 400
    unknown = app_session(client, "nobody", code, verifier)
    assert unknown.status_code == 401

    # An assistant's code (for tokens) logs no one in.
    assistant = register(client)
    code = consent(ada, assistant, challenge)["code"][0]
    response = client.post(
        "/api/oauth/app-session",
        json={
            "client_id": assistant,
            "code": code,
            "redirect_uri": REDIRECT,
            "code_verifier": verifier,
        },
    )
    assert response.json()["error_description"] == (
        "This code is for tokens, not a login."
    )

    # Only to an app on this computer.
    request = {
        "client_id": assistant,
        "redirect_uri": REDIRECT,
        "code_challenge": challenge,
    }
    refused = ada.post("/api/oauth/app-login/check", json=request)
    assert refused.status_code == 400
    assert "paperus app" in refused.json()["detail"]
    asked = oauth.check_request(
        db,
        client_id=assistant,
        redirect_uri=REDIRECT,
        response_type="code",
        code_challenge=challenge,
        code_challenge_method="S256",
        scope=None,
    )
    user = db.scalar(select(User).where(User.username == "ada"))
    assert user is not None
    with pytest.raises(oauth.OAuthError):
        oauth.create_app_code(db, asked, user, challenge)
