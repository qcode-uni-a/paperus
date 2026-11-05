from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from paperus.api.deps import SESSION_COOKIE
from paperus.auth import create_user, hash_password, verify_password
from paperus.models import LoginSession


def test_password_hashing() -> None:
    password_hash = hash_password("correct horse")
    assert password_hash != "correct horse"
    assert verify_password(password_hash, "correct horse")
    assert not verify_password(password_hash, "wrong")
    assert not verify_password("not a hash", "correct horse")


def make_user(db: Session, username: str = "ada", password: str = "secret") -> None:
    create_user(db, username, password)
    db.commit()


def login(client: TestClient, username: str = "ada", password: str = "secret") -> str:
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200
    token: str = response.json()["token"]
    return token


def test_login_sets_cookie_and_returns_user(client: TestClient, db: Session) -> None:
    make_user(db)
    response = client.post(
        "/api/auth/login", json={"username": "ada", "password": "secret"}
    )
    assert response.status_code == 200
    assert response.json()["user"]["username"] == "ada"
    assert response.cookies[SESSION_COOKIE] == response.json()["token"]
    assert client.get("/api/auth/me").json()["username"] == "ada"


def test_bearer_token(client: TestClient, db: Session) -> None:
    make_user(db)
    token = login(client)
    client.cookies.clear()
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def test_wrong_password_and_unknown_user(client: TestClient, db: Session) -> None:
    make_user(db)
    for username, password in [("ada", "wrong"), ("nobody", "secret")]:
        response = client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )
        assert response.status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_logout_ends_session(client: TestClient, db: Session) -> None:
    make_user(db)
    token = login(client)
    assert client.post("/api/auth/logout").status_code == 204
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_expired_session(client: TestClient, db: Session) -> None:
    make_user(db)
    login(client)
    db.execute(
        update(LoginSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_cookie_is_secure_by_default(client: TestClient, db: Session) -> None:
    make_user(db)
    response = client.post(
        "/api/auth/login", json={"username": "ada", "password": "secret"}
    )
    cookie = response.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie


def test_change_password(client: TestClient, db: Session) -> None:
    make_user(db)
    other_device = login(client)
    client.cookies.clear()
    this_device = login(client)
    client.cookies.clear()
    headers = {"Authorization": f"Bearer {this_device}"}

    wrong = {"current": "wrong", "new": "a new password"}
    assert (
        client.post("/api/auth/password", json=wrong, headers=headers).status_code
        == 403
    )
    short = {"current": "secret", "new": "short"}
    assert (
        client.post("/api/auth/password", json=short, headers=headers).status_code
        == 422
    )
    body = {"current": "secret", "new": "a new password"}
    assert (
        client.post("/api/auth/password", json=body, headers=headers).status_code == 204
    )

    # This device stays logged in, the other one is logged out.
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    other = {"Authorization": f"Bearer {other_device}"}
    assert client.get("/api/auth/me", headers=other).status_code == 401
    assert login(client, password="a new password")


def test_hints_are_remembered(client: TestClient, db: Session) -> None:
    make_user(db)
    login(client)
    assert client.get("/api/auth/me").json()["seen_hints"] == []
    assert client.put("/api/auth/hints/first-owner").status_code == 204
    client.put("/api/auth/hints/first-owner")
    assert client.get("/api/auth/me").json()["seen_hints"] == ["first-owner"]
    assert client.put("/api/auth/hints/Not%20a%20hint").status_code == 422
