"""Both storage backends behave the same; S3 is emulated with moto."""

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber
from fastapi import FastAPI
from fastapi.testclient import TestClient
from moto import mock_aws

from paperus.config import Settings
from paperus.storage import (
    BlobStore,
    FilesystemStore,
    S3Store,
    TooLarge,
    make_blob_store,
)

CONTENT = b"%PDF-1.7\n" + b"x" * 3000


@pytest.fixture
def s3_bucket() -> Iterator[str]:
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="papers")
        yield "papers"


@pytest.fixture(params=["filesystem", "s3"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[BlobStore]:
    if request.param == "filesystem":
        yield FilesystemStore(tmp_path / "files")
        return
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="papers")
        yield S3Store(client, "papers", prefix="lib/", temp_dir=tmp_path / "tmp")


def test_put_and_read(store: BlobStore) -> None:
    stored = store.put([CONTENT[:100], CONTENT[100:]], max_size=10_000)
    assert stored.sha256 == hashlib.sha256(CONTENT).digest()
    assert stored.size == len(CONTENT)
    assert stored.head == CONTENT[:1024]
    assert store.exists(stored.sha256)
    assert b"".join(store.iter_bytes(stored.sha256)) == CONTENT
    with store.local_file(stored.sha256) as path:
        assert path.read_bytes() == CONTENT
    assert not any(store.temp_dir.iterdir())


def test_same_content_twice(store: BlobStore) -> None:
    first = store.put([CONTENT], max_size=10_000)
    second = store.put([CONTENT], max_size=10_000)
    assert first == second
    assert not any(store.temp_dir.iterdir())


def test_too_large_leaves_nothing(store: BlobStore) -> None:
    with pytest.raises(TooLarge):
        store.put([CONTENT], max_size=100)
    assert not store.exists(hashlib.sha256(CONTENT).digest())
    assert not any(store.temp_dir.iterdir())


def test_delete(store: BlobStore) -> None:
    stored = store.put([CONTENT], max_size=10_000)
    store.delete(stored.sha256)
    assert not store.exists(stored.sha256)


def test_s3_keys_use_prefix(s3_bucket: str, tmp_path: Path) -> None:
    client = boto3.client("s3", region_name="us-east-1")
    store = S3Store(client, s3_bucket, prefix="/lib/", temp_dir=tmp_path)
    stored = store.put([CONTENT], max_size=10_000)
    name = stored.sha256.hex()
    keys = [o["Key"] for o in client.list_objects_v2(Bucket=s3_bucket)["Contents"]]
    assert keys == [f"lib/blobs/{name[:2]}/{name[2:4]}/{name}"]


def test_make_blob_store(tmp_path: Path) -> None:
    assert isinstance(make_blob_store(Settings(storage_path=tmp_path)), FilesystemStore)
    with pytest.raises(ValueError, match="S3_BUCKET"):
        make_blob_store(Settings(storage_backend="s3"))


def test_api_with_s3(
    s3_bucket: str,
    settings: Settings,
    logged_in: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = S3Store(
        boto3.client("s3", region_name="us-east-1"),
        s3_bucket,
        temp_dir=settings.storage_path,
    )
    app = logged_in.app
    assert isinstance(app, FastAPI)
    monkeypatch.setattr(app.state, "blobs", store)
    item = logged_in.post("/api/items", json={"metadata": {"title": "S3"}}).json()
    file = logged_in.post(
        f"/api/items/{item['id']}/files",
        files={"upload": ("ä b.pdf", CONTENT, "application/pdf")},
    ).json()
    response = logged_in.get(f"/api/files/{file['id']}/content")
    assert response.status_code == 200
    assert response.content == CONTENT
    assert response.headers["content-length"] == str(len(CONTENT))
    assert (
        response.headers["content-disposition"]
        == "inline; filename*=utf-8''%C3%A4%20b.pdf"
    )


def test_listing_what_is_stored(store: BlobStore) -> None:
    stored = store.put([CONTENT], max_size=10_000)
    # Not a SHA-256 (64 characters, but not hex): left out.
    odd = "z" * 64
    if isinstance(store, FilesystemStore):
        folder = store.root / "blobs" / "zz" / "zz"
        folder.mkdir(parents=True)
        (folder / odd).write_bytes(b"?")
    else:
        assert isinstance(store, S3Store)
        store.client.put_object(
            Bucket="papers", Key=f"lib/blobs/zz/zz/{odd}", Body=b"?"
        )
    [(sha256, written, size)] = store.iter_stored()
    assert (sha256, size) == (stored.sha256, len(CONTENT))
    assert abs(datetime.now(UTC) - written) < timedelta(minutes=1)


def test_s3_errors_other_than_missing(s3_bucket: str, tmp_path: Path) -> None:
    client = boto3.client("s3", region_name="us-east-1")
    store = S3Store(client, s3_bucket, temp_dir=tmp_path)
    with Stubber(client) as stub:
        stub.add_client_error("head_object", "AccessDenied", http_status_code=403)
        with pytest.raises(ClientError):
            store.exists(hashlib.sha256(CONTENT).digest())


def test_make_s3_store(s3_bucket: str, tmp_path: Path) -> None:
    settings = Settings(
        storage_backend="s3",
        s3_bucket=s3_bucket,
        s3_prefix="lib",
        s3_region="us-east-1",
        temp_path=tmp_path,
    )
    store = make_blob_store(settings)
    assert isinstance(store, S3Store) and store.prefix == "lib/"
    stored = store.put([CONTENT], max_size=10_000)
    assert store.exists(stored.sha256)
