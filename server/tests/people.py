"""Several logged-in people on one test client, for permission tests."""

from collections.abc import Mapping, Sequence
from typing import Any

import httpx2
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus.auth import create_user


class Person:
    """One logged-in person, with their own token on the shared test client."""

    def __init__(
        self, client: TestClient, db: Session, name: str, *, admin: bool = False
    ) -> None:
        create_user(db, name, "secret", is_admin=admin)
        db.commit()
        token = client.post(
            "/api/auth/login", json={"username": name, "password": "secret"}
        ).json()["token"]
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}"}
        self.id: str = client.get("/api/auth/me", headers=self.headers).json()["id"]

    def get(
        self, url: str, params: Mapping[str, str | bool | list[str]] | None = None
    ) -> httpx2.Response:
        return self.client.get(url, headers=self.headers, params=params)

    def post(
        self,
        url: str,
        json: object = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> httpx2.Response:
        return self.client.post(url, headers=self.headers, json=json, files=files)

    def put(self, url: str, json: object = None) -> httpx2.Response:
        return self.client.put(url, headers=self.headers, json=json)

    def patch(
        self, url: str, json: object, headers: dict[str, str] | None = None
    ) -> httpx2.Response:
        return self.client.patch(
            url, headers={**self.headers, **(headers or {})}, json=json
        )

    def delete(self, url: str) -> httpx2.Response:
        return self.client.delete(url, headers=self.headers)

    def libraries(self) -> dict[str, dict[str, Any]]:
        return {lib["name"]: lib for lib in self.get("/api/libraries").json()}

    def add(self, title: str, library: str | None = None) -> dict[str, Any]:
        response = self.post(
            "/api/items", json={"metadata": {"title": title}, "library_id": library}
        )
        assert response.status_code == 201, response.text
        result: dict[str, Any] = response.json()
        return result

    def note(
        self, text: str, library: str | None = None, items: Sequence[str] = ()
    ) -> dict[str, Any]:
        response = self.post(
            "/api/notes",
            json={
                "text": text,
                "library_id": library,
                "items": [{"item_id": i} for i in items],
            },
        )
        assert response.status_code == 201, response.text
        result: dict[str, Any] = response.json()
        return result

    def titles(self, **params: str) -> list[str]:
        return sorted(i["title"] for i in self.get("/api/items", params=params).json())


def group(
    admin: Person, name: str, first_admin: Person, parent: str | None = None
) -> dict[str, Any]:
    response = admin.post(
        "/api/groups",
        json={"name": name, "parent_id": parent, "admin_id": first_admin.id},
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result
