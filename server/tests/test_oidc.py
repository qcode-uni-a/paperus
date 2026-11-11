"""Authentication settings: OIDC login (OpenID Connect), password
login, session length, password length, logging everyone out."""

import base64
import json
import socket
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from fastapi.testclient import TestClient
from procrastinate import App
from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus import avatars, oidc
from paperus.app import create_app
from paperus.auth import create_user
from paperus.config import Settings
from paperus.models import User
from paperus.system import SystemConfig, oidc_secret
from tests.conftest import FakeDOIRegistry, FakeML

ISSUER = "https://idp.test/realms/uni"
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR"
    + (96).to_bytes(4)
    + (96).to_bytes(4)
    + b"\x00" * 100
)


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
        self.pictures = 0

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
        if path.endswith("/pic.png"):
            self.pictures += 1
            return httpx2.Response(200, content=PNG)
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


def enable_oidc(client: TestClient, **change: Any) -> None:  # noqa: ANN401
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


def log_in_with_oidc(
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


def test_oidc_linked_creates_an_account(
    site: TestClient, provider: FakeProvider, db: Session
) -> None:
    assert site.get("/api/auth/methods").json() == {
        "password": True,
        "oidc_label": None,
    }
    enable_oidc(site)
    assert site.get("/api/auth/methods").json()["oidc_label"] == "Uni login"

    back = log_in_with_oidc(site, provider)
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
    log_in_with_oidc(site, provider)
    assert site.get("/api/auth/me").json()["username"] == "ada.l"


def test_existing_account_is_linked(
    site: TestClient, provider: FakeProvider, db: Session
) -> None:
    create_user(db, "ada.l", "password1")
    db.commit()
    enable_oidc(site, oidc_create_accounts=False)
    log_in_with_oidc(site, provider)
    assert site.get("/api/auth/me").json()["username"] == "ada.l"


def test_no_account_without_creating(site: TestClient, provider: FakeProvider) -> None:
    enable_oidc(site, oidc_create_accounts=False)
    back = log_in_with_oidc(site, provider)
    assert back.headers["location"].startswith("https://testserver/login?error=")
    assert "ask%20an%20administrator" in back.headers["location"]


def test_refused_logins(site: TestClient, provider: FakeProvider) -> None:
    enable_oidc(site)
    assert "error=" in log_in_with_oidc(site, provider, "bad").headers["location"]
    provider.audience = "someone-else"
    assert "another%20client" in log_in_with_oidc(site, provider).headers["location"]
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
    enable_oidc(site, password_login=False)
    create_user(db, "ben", "password1")
    db.commit()
    refused = site.post(
        "/api/auth/login", json={"username": "ben", "password": "password1"}
    )
    assert refused.status_code == 403
    assert "Uni login" in refused.json()["detail"]
    # Administrators still may (a way in if the OIDC login fails).
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
    enable_oidc(site)
    assert site.get("/api/auth/me").json()["oidc_linked"] is False
    back = log_in_with_oidc(site, provider, link=True)
    assert back.headers["location"] == "https://testserver/collections"
    me = site.get("/api/auth/me").json()
    assert me["username"] == "root"
    assert me["oidc_linked"] is True
    # Now the OIDC login logs in as root, despite the other name.
    log_in_with_oidc(site, provider)
    assert site.get("/api/auth/me").json()["username"] == "root"
    assert db.scalar(select(User).where(User.username == "ada.l")) is None

    # A login linked to root cannot be linked to another account.
    create_user(db, "ben", "password1")
    db.commit()
    site.post("/api/auth/login", json={"username": "ben", "password": "password1"})
    taken = log_in_with_oidc(site, provider, link=True)
    assert "link_error=" in taken.headers["location"]
    assert "root" in taken.headers["location"]

    site.post("/api/auth/login", json={"username": "root", "password": "secret12"})
    assert site.delete("/api/auth/oidc/link").status_code == 204
    assert site.get("/api/auth/me").json()["oidc_linked"] is False


def test_picture_from_the_identity_provider(
    site: TestClient, provider: FakeProvider, db: Session
) -> None:
    enable_oidc(site)
    provider.person["picture"] = f"{ISSUER}/pic.png"
    log_in_with_oidc(site, provider)
    me = site.get("/api/auth/me").json()
    assert me["avatar_url"] is not None
    assert site.get(me["avatar_url"]).content == PNG
    # Only when linking: later logins fetch nothing.
    log_in_with_oidc(site, provider)
    assert provider.pictures == 1


def test_no_picture_from_elsewhere(site: TestClient, provider: FakeProvider) -> None:
    enable_oidc(site)
    # Another host that does not resolve to a public address; plain http.
    for url in ("https://pictures.internal.test/pic.png", "http://idp.test/pic.png"):
        provider.person = {"sub": url, "preferred_username": f"p{len(url)}"}
        provider.person["picture"] = url
        assert log_in_with_oidc(site, provider).status_code == 303
        assert site.get("/api/auth/me").json()["avatar_url"] is None
    assert provider.pictures == 0


# The steps one by one, against providers that misbehave.


def http(handler: Any) -> httpx2.Client:  # noqa: ANN401 (a request handler)
    return httpx2.Client(transport=httpx2.MockTransport(handler))


def discovery(**change: Any) -> httpx2.Client:  # noqa: ANN401
    """A provider whose discovery document has these changes (None: left
    out)."""
    document = {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/auth",
        "token_endpoint": f"{ISSUER}/token",
        **change,
    }
    found = {key: value for key, value in document.items() if value is not None}
    return http(lambda request: httpx2.Response(200, json=found))


@pytest.mark.parametrize(
    ("client", "error"),
    [
        (http(lambda request: httpx2.Response(500)), "did not answer"),
        (http(lambda request: httpx2.Response(200, text="<html>")), "did not answer"),
        (discovery(issuer="https://other.test"), "calls itself"),
        (discovery(token_endpoint=None), "lacks 'token_endpoint'"),
        (discovery(token_endpoint="http://idp.test/token"), "must use https"),
    ],
)
def test_discovery_failures(
    provider: FakeProvider,  # empties the cache
    client: httpx2.Client,
    error: str,
) -> None:
    with pytest.raises(oidc.LoginFailed, match=error):
        oidc.discover(client, ISSUER)


def test_discovery_is_cached() -> None:
    oidc._discovered.clear()
    asked: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        asked.append(request)
        return httpx2.Response(
            200,
            json={
                "issuer": f"{ISSUER}/",
                "authorization_endpoint": f"{ISSUER}/auth?kc=1",
                "token_endpoint": f"{ISSUER}/token",
            },
        )

    found = oidc.discover(http(answer), f"{ISSUER}/")
    assert oidc.discover(http(answer), ISSUER) is found
    assert len(asked) == 1
    oidc.discover(http(answer), ISSUER, fresh=True)
    assert len(asked) == 2
    # The endpoint's own query stays.
    assert oidc.start(found, "paperus", "https://x/cb").url.startswith(
        f"{ISSUER}/auth?kc=1&response_type=code"
    )
    oidc._discovered.clear()


PROVIDER = oidc.Provider(
    issuer=ISSUER,
    authorization_endpoint=f"{ISSUER}/auth",
    token_endpoint=f"{ISSUER}/token",
    userinfo_endpoint=f"{ISSUER}/userinfo",
)


def finish(
    tokens: dict[str, Any] | httpx2.Response,
    userinfo: Any = None,  # noqa: ANN401 (any JSON, or a response)
    nonce: str = "n-1",
) -> dict[str, Any]:
    def answer(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/token"):
            if isinstance(tokens, httpx2.Response):
                return tokens
            return httpx2.Response(200, json=tokens)
        if isinstance(userinfo, httpx2.Response):
            return userinfo
        return httpx2.Response(200, json=userinfo)

    return oidc.finish(
        http(answer),
        PROVIDER,
        client_id="paperus",
        client_secret=None,
        redirect_uri="https://testserver/api/auth/oidc/callback",
        code="good",
        verifier="v",
        nonce=nonce,
    )


def id_token(**change: Any) -> dict[str, Any]:  # noqa: ANN401
    claims = {
        "iss": ISSUER,
        "aud": ["other", "paperus"],
        "exp": time.time() + 300,
        "nonce": "n-1",
        "sub": "u-1",
        "name": "From the token",
        **change,
    }
    return {"id_token": _jwt(claims), "access_token": "at"}


def test_finish_takes_userinfo_of_the_same_person() -> None:
    claims = finish(id_token(), {"sub": "u-1", "name": "Info", "email": "a@b.c"})
    # The ID token's claims win over userinfo's.
    assert (claims["name"], claims["email"]) == ("From the token", "a@b.c")
    # Userinfo about someone else, or none at all, is ignored.
    assert "email" not in finish(id_token(), {"sub": "u-2", "email": "x@y.z"})
    assert finish(id_token(), ["not", "a", "dict"])["sub"] == "u-1"
    assert finish(id_token(), httpx2.Response(502, text="bad gateway"))["sub"] == "u-1"


@pytest.mark.parametrize(
    ("tokens", "error"),
    [
        (httpx2.Response(200, text="not json"), "did not answer"),
        (
            httpx2.Response(400, json={"error_description": "code expired"}),
            "refused the login: code expired",
        ),
        (httpx2.Response(503, json={}), "refused the login: 503"),
        ({"access_token": "at"}, "refused the login: 200"),
        ({"id_token": "no-dots"}, "unreadable ID token"),
        ({"id_token": "a.!!!.c"}, "unreadable ID token"),
        ({"id_token": "a.WzFd.c"}, "unreadable ID token"),  # a list: [1]
        (id_token(iss="https://evil.test"), "another issuer"),
        (id_token(aud="someone-else"), "another client"),
        (id_token(exp=time.time() - 3600), "expired"),
        (id_token(exp="tomorrow"), "expired"),
        (id_token(nonce="replayed"), "nonce"),
        (id_token(sub=""), "no sub"),
    ],
)
def test_finish_refuses(tokens: dict[str, Any] | httpx2.Response, error: str) -> None:
    with pytest.raises(oidc.LoginFailed, match=error):
        finish(tokens)


def test_finish_when_the_provider_is_down() -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("unreachable")

    with pytest.raises(oidc.LoginFailed, match="did not answer"):
        oidc.finish(
            http(down),
            PROVIDER,
            client_id="paperus",
            client_secret="s",
            redirect_uri="https://x/cb",
            code="c",
            verifier="v",
            nonce="n",
        )


def test_accounts_for_claims(db: Session) -> None:
    config = SystemConfig(embedding_model="bge-m3")
    claims = {"iss": ISSUER, "sub": "u-1", "preferred_username": "no spaces!"}
    with pytest.raises(oidc.LoginFailed, match="no usable preferred_username"):
        oidc.user_for(db, claims, config)
    # An account of that name, already linked to another login.
    ben = create_user(db, "ben", "password1")
    ben.oidc_subject = f"{ISSUER} u-0"
    with pytest.raises(oidc.LoginFailed, match="belongs to another login"):
        oidc.user_for(db, {**claims, "preferred_username": "ben"}, config)
    # An administrator's account is not taken over by its name.
    create_user(db, "admin", "password1").is_admin = True
    with pytest.raises(oidc.LoginFailed, match="an administrator's"):
        oidc.user_for(db, {**claims, "preferred_username": "admin"}, config)
    # The login linked to a deactivated account.
    ben.deactivated_at = datetime.now(UTC)
    with pytest.raises(oidc.LoginFailed, match="deactivated"):
        oidc.user_for(db, {**claims, "sub": "u-0"}, config)
    db.rollback()


def test_pictures_only_from_safe_places(
    provider: FakeProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = User(username="ada")
    client = http(provider)
    # Missing, or not an image: skipped, the login goes on.
    oidc.take_picture(client, user, {"picture": f"{ISSUER}/gone.png"}, ISSUER)

    def text(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"<svg/>")

    oidc.take_picture(http(text), user, {"picture": f"{ISSUER}/x.svg"}, ISSUER)
    assert user.avatar_version is None
    oidc.take_picture(client, user, {"picture": f"{ISSUER}/pic.png"}, ISSUER)
    assert user.avatar == PNG

    def huge(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"\x00" * (avatars.MAX_BYTES + 1))

    assert oidc.fetch_picture(http(huge), f"{ISSUER}/big.png", ISSUER) is None
    assert oidc.fetch_picture(client, "https:///pic.png", ISSUER) is None
    # Another host is asked only if all its addresses are public.
    assert oidc.fetch_picture(client, "https://localhost/pic.png", ISSUER) is None
    assert oidc.fetch_picture(client, "https://1.1.1.1/pic.png", ISSUER) == PNG

    def unknown(*args: object, **kwargs: object) -> None:
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", unknown)
    assert oidc.fetch_picture(client, "https://nowhere.test/pic.png", ISSUER) is None


def test_login_redirects_when_something_is_wrong(
    site: TestClient, provider: FakeProvider
) -> None:
    def start(query: str = "") -> str:
        response = site.get(f"/api/auth/oidc/start{query}", follow_redirects=False)
        assert response.status_code == 303
        location: str = response.headers["location"]
        return location

    off = start("?next=//evil.test")
    assert off == "https://testserver/login?error=The%20OIDC%20login%20is%20off."
    # Linking: back to the page one came from (only one of this site).
    assert start("?next=/settings?tab=me&link=true").startswith(
        "https://testserver/settings?tab=me&link_error=The%20OIDC"
    )
    enable_oidc(site)
    # Behind a proxy: the address set in the administration.
    configure(site, public_url="https://library.example/")
    assert parse_qs(urlsplit(start()).query)["redirect_uri"] == [
        "https://library.example/api/auth/oidc/callback"
    ]
    configure(site, public_url=None, oidc_issuer="https://idp.test/realms/gone")
    assert "calls%20itself" in start()

    site.cookies.clear()
    assert "Log%20in%20first" in start("?link=true")
    # Back without the cookie (it lasts ten minutes).
    late = site.get(
        "/api/auth/oidc/callback",
        params={"code": "good", "state": "s"},
        follow_redirects=False,
    )
    assert "took%20too%20long" in late.headers["location"]


def test_callback_errors(site: TestClient, provider: FakeProvider) -> None:
    enable_oidc(site)

    def back(**params: str) -> str:
        site.get("/api/auth/oidc/start", follow_redirects=False)
        response = site.get(
            "/api/auth/oidc/callback", params=params, follow_redirects=False
        )
        location: str = response.headers["location"]
        return location

    # The person declined at the provider.
    declined = back(error="access_denied", error_description="You said no")
    assert "OIDC%20login%20failed%3A%20You%20said%20no." in declined
    assert "access_denied" in back(error="access_denied")
    # The administration turned it off meanwhile.
    start = site.get("/api/auth/oidc/start", follow_redirects=False)
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    configure(site, oidc_enabled=False)
    off = site.get(
        "/api/auth/oidc/callback",
        params={"code": "good", "state": state},
        follow_redirects=False,
    )
    assert "login%20is%20off" in off.headers["location"]


def test_link_after_logging_out(site: TestClient, provider: FakeProvider) -> None:
    enable_oidc(site)
    start = site.get("/api/auth/oidc/start?link=true", follow_redirects=False)
    query = parse_qs(urlsplit(start.headers["location"]).query)
    provider.nonce = query["nonce"][0]
    site.post("/api/auth/logout")
    back = site.get(
        "/api/auth/oidc/callback",
        params={"code": "good", "state": query["state"][0]},
        follow_redirects=False,
    )
    assert "logged%20out%20meanwhile" in back.headers["location"]
    assert "link_error=" in back.headers["location"]


def test_oidc_settings_must_fit(
    site: TestClient, db: Session, settings: Settings
) -> None:
    half = configure(site, oidc_enabled=True, oidc_issuer=ISSUER)
    assert half.status_code == 422
    assert "issuer and a client ID" in half.text
    # A secret from the environment wins over one set in the administration.
    enable_oidc(site)
    assert oidc_secret(db, settings) == "s3cret"
    from_environment = settings.model_copy(update={"oidc_client_secret": "env"})
    assert oidc_secret(db, from_environment) == "env"
