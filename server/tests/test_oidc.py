"""Authentication settings: university login (OpenID Connect), password
login, session length, password length, logging everyone out."""

import base64
import json
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from fastapi.testclient import TestClient
from procrastinate import App
from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus import oidc
from paperus.app import create_app
from paperus.auth import create_user
from paperus.config import Settings
from paperus.models import User
from tests.conftest import FakeDOIRegistry, FakeML

ISSUER = "https://idp.test/realms/uni"


def _jwt(claims: dict[str, Any]) -> str:
    def part(data: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'RS256'})}.{part(claims)}.c2ln"


class FakeProvider:
    """An identity provider: discovery, token and userinfo endpoints."""

    def __init__(self) -> None:
        self.person: dict[str, Any] = {"sub": "u-1", "preferred_username": "ada.l"}
        self.nonce = ""
        self.forms: list[dict[str, list[str]]] = []
        self.audience = "paperus"

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            return httpx2.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/auth",
                    "token_endpoint": f"{ISSUER}/token",
                    "userinfo_endpoint": f"{ISSUER}/userinfo",
                },
            )
        if path.endswith("/token"):
            form = parse_qs(request.content.decode())
            self.forms.append(form)
            if form["code"] != ["good"]:
                return httpx2.Response(400, json={"error": "invalid_grant"})
            claims = {
                "iss": ISSUER,
                "aud": self.audience,
                "exp": int(time.time()) + 300,
                "nonce": self.nonce,
                "sub": self.person["sub"],
            }
            return httpx2.Response(
                200, json={"id_token": _jwt(claims), "access_token": "at"}
            )
        if path.endswith("/userinfo"):
            return httpx2.Response(200, json=self.person)
        return httpx2.Response(404)


@pytest.fixture
def provider() -> FakeProvider:
    oidc._discovered.clear()
    return FakeProvider()


@pytest.fixture
def site(
    settings: Settings,
    db: Session,
    doi_registry: FakeDOIRegistry,
    job_app: App,
    fake_ml: FakeML,
    provider: FakeProvider,
) -> Iterator[TestClient]:
    def route(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "idp.test":
            return provider(request)
        return doi_registry(request)

    app = create_app(
        settings,
        http_client=httpx2.Client(transport=httpx2.MockTransport(route)),
        job_app=job_app,
        ml_client=fake_ml.client(),
    )
    with TestClient(app, base_url="https://testserver") as client:
        create_user(db, "root", "secret12", is_admin=True)
        db.commit()
        login = client.post(
            "/api/auth/login", json={"username": "root", "password": "secret12"}
        )
        assert login.status_code == 200
        yield client


def configure(client: TestClient, **change: Any) -> httpx2.Response:  # noqa: ANN401
    config = client.get("/api/admin/config").json()
    return client.put("/api/admin/config", json={**config, **change})


def university(client: TestClient, **change: Any) -> None:  # noqa: ANN401
    response = configure(
        client,
        oidc_enabled=True,
        oidc_issuer=ISSUER,
        oidc_client_id="paperus",
        oidc_label="Uni login",
        **change,
    )
    assert response.status_code == 200, response.text
    assert (
        client.put(
            "/api/admin/authentication/secret", json={"secret": "s3cret"}
        ).status_code
        == 204
    )


def log_in_at_university(
    client: TestClient, provider: FakeProvider, code: str = "good", link: bool = False
) -> httpx2.Response:
    start = client.get(
        f"/api/auth/oidc/start?next=/collections&link={str(link).lower()}",
        follow_redirects=False,
    )
    assert start.status_code == 303
    target = urlsplit(start.headers["location"])
    assert f"{target.scheme}://{target.netloc}{target.path}" == f"{ISSUER}/auth"
    query = parse_qs(target.query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == ["https://testserver/api/auth/oidc/callback"]
    provider.nonce = query["nonce"][0]
    return client.get(
        "/api/auth/oidc/callback",
        params={"code": code, "state": query["state"][0]},
        follow_redirects=False,
    )


def test_university_login_creates_an_account(
    site: TestClient, provider: FakeProvider, db: Session
) -> None:
    assert site.get("/api/auth/methods").json() == {
        "password": True,
        "oidc_label": None,
    }
    university(site)
    assert site.get("/api/auth/methods").json()["oidc_label"] == "Uni login"

    back = log_in_at_university(site, provider)
    assert back.status_code == 303, back.text
    assert back.headers["location"] == "https://testserver/collections"
    assert site.get("/api/auth/me").json()["username"] == "ada.l"
    assert provider.forms[0]["client_secret"] == ["s3cret"]
    assert provider.forms[0]["code_verifier"]
    user = db.scalar(select(User).where(User.username == "ada.l"))
    assert user is not None
    assert user.oidc_subject == f"{ISSUER} u-1"

    # The second time: the same account, even under another name.
    provider.person["preferred_username"] = "ada.lovelace"
    log_in_at_university(site, provider)
    assert site.get("/api/auth/me").json()["username"] == "ada.l"


def test_existing_account_is_linked(
    site: TestClient, provider: FakeProvider, db: Session
) -> None:
    create_user(db, "ada.l", "password1")
    db.commit()
    university(site, oidc_create_accounts=False)
    log_in_at_university(site, provider)
    assert site.get("/api/auth/me").json()["username"] == "ada.l"


def test_no_account_without_creating(site: TestClient, provider: FakeProvider) -> None:
    university(site, oidc_create_accounts=False)
    back = log_in_at_university(site, provider)
    assert back.headers["location"].startswith("https://testserver/login?error=")
    assert "ask%20an%20administrator" in back.headers["location"]


def test_refused_logins(site: TestClient, provider: FakeProvider) -> None:
    university(site)
    assert "error=" in log_in_at_university(site, provider, "bad").headers["location"]
    provider.audience = "someone-else"
    assert (
        "another%20client" in log_in_at_university(site, provider).headers["location"]
    )
    # A callback for a login not started here.
    site.get("/api/auth/oidc/start", follow_redirects=False)
    stray = site.get(
        "/api/auth/oidc/callback",
        params={"code": "good", "state": "forged"},
        follow_redirects=False,
    )
    assert "not%20started%20here" in stray.headers["location"]
    # The person still is root.
    assert site.get("/api/auth/me").json()["username"] == "root"


def test_check_provider(site: TestClient) -> None:
    found = site.post("/api/admin/authentication/check", json={"issuer": ISSUER})
    assert found.json() == {
        "ok": True,
        "error": None,
        "authorization_endpoint": f"{ISSUER}/auth",
    }
    insecure = site.post(
        "/api/admin/authentication/check", json={"issuer": "http://idp.test"}
    )
    assert "https" in insecure.json()["error"]
    info = site.get("/api/admin/authentication").json()
    assert info["redirect_uri"] == "https://testserver/api/auth/oidc/callback"
    assert info["secret_set"] is False
    assert info["sessions"] == 1


def test_password_login_off(
    site: TestClient, provider: FakeProvider, db: Session
) -> None:
    # Not without another way to log in.
    assert configure(site, password_login=False).status_code == 422
    university(site, password_login=False)
    create_user(db, "ben", "password1")
    db.commit()
    refused = site.post(
        "/api/auth/login", json={"username": "ben", "password": "password1"}
    )
    assert refused.status_code == 403
    assert "Uni login" in refused.json()["detail"]
    # Administrators still may (a way in if the university login fails).
    admin = site.post(
        "/api/auth/login", json={"username": "root", "password": "secret12"}
    )
    assert admin.status_code == 200


def test_session_and_password_length(site: TestClient) -> None:
    assert configure(site, session_days=7, password_min_length=12).status_code == 200
    login = site.post(
        "/api/auth/login", json={"username": "root", "password": "secret12"}
    )
    assert "Max-Age=604800" in login.headers["set-cookie"]
    short = site.post(
        "/api/admin/users", json={"username": "cy", "password": "elevenchars"}
    )
    assert short.status_code == 422
    assert "12 characters" in short.json()["detail"]
    long = site.post(
        "/api/admin/users", json={"username": "cy", "password": "twelve chars"}
    )
    assert long.status_code == 201


def test_log_everyone_out(site: TestClient, db: Session) -> None:
    create_user(db, "ben", "password1")
    db.commit()
    login = site.post(
        "/api/auth/login", json={"username": "ben", "password": "password1"}
    )
    ben = {"Authorization": f"Bearer {login.json()['token']}"}
    site.post("/api/auth/login", json={"username": "root", "password": "secret12"})
    assert site.delete("/api/admin/sessions").json() == {"ended": 2}  # ben, root before
    assert site.get("/api/auth/me", headers=ben).status_code == 401
    assert site.get("/api/auth/me").status_code == 200


def test_link_the_logged_in_account(
    site: TestClient, provider: FakeProvider, db: Session
) -> None:
    university(site)
    assert site.get("/api/auth/me").json()["university_login"] is False
    back = log_in_at_university(site, provider, link=True)
    assert back.headers["location"] == "https://testserver/collections"
    me = site.get("/api/auth/me").json()
    assert me["username"] == "root"
    assert me["university_login"] is True
    # Now the university login logs in as root, despite the other name.
    log_in_at_university(site, provider)
    assert site.get("/api/auth/me").json()["username"] == "root"
    assert db.scalar(select(User).where(User.username == "ada.l")) is None

    # A login linked to root cannot be linked to another account.
    create_user(db, "ben", "password1")
    db.commit()
    site.post("/api/auth/login", json={"username": "ben", "password": "password1"})
    taken = log_in_at_university(site, provider, link=True)
    assert "link_error=" in taken.headers["location"]
    assert "root" in taken.headers["location"]

    site.post("/api/auth/login", json={"username": "root", "password": "secret12"})
    assert site.delete("/api/auth/oidc/link").status_code == 204
    assert site.get("/api/auth/me").json()["university_login"] is False
