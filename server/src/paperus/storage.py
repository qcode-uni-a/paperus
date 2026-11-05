"""Content-addressed storage for file contents (blobs).

Each content is stored once under its SHA-256. Two backends:

- ``FilesystemStore``: any mounted path, e.g. a local disk, NFS or SMB share.
  Uploads go to ``tmp/`` on the same mount and are renamed into place, which
  is atomic there too; names are lowercase hex, so case-insensitive shares
  are fine.
- ``S3Store``: S3 or a compatible service (MinIO, Ceph, …).
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Generator, Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import ClientError

from paperus.config import Settings

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client

READ_CHUNK = 1024 * 1024


class TooLarge(ValueError):
    pass


@dataclass(frozen=True)
class StoredBlob:
    sha256: bytes
    size: int
    head: bytes
    """The first bytes, for checking the file type."""


def blob_name(sha256: bytes) -> str:
    """``ab/cd/abcd…``: two levels of folders keep directories small."""
    name = sha256.hex()
    return f"{name[:2]}/{name[2:4]}/{name}"


class BlobStore(ABC):
    HEAD_SIZE = 1024

    def __init__(self, temp_dir: Path) -> None:
        self.temp_dir = temp_dir
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def put(self, chunks: Iterable[bytes], *, max_size: int) -> StoredBlob:
        """Store the chunks, hashing on the way; keep an existing copy."""
        digest = hashlib.sha256()
        size = 0
        head = b""
        fd, tmp_name = tempfile.mkstemp(dir=self.temp_dir)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as out:
                for chunk in chunks:
                    size += len(chunk)
                    if size > max_size:
                        raise TooLarge(size)
                    if len(head) < self.HEAD_SIZE:
                        head += chunk[: self.HEAD_SIZE - len(head)]
                    digest.update(chunk)
                    out.write(chunk)
            sha256 = digest.digest()
            self._commit(tmp, sha256)
        finally:
            tmp.unlink(missing_ok=True)
        return StoredBlob(sha256=sha256, size=size, head=head)

    @abstractmethod
    def _commit(self, tmp: Path, sha256: bytes) -> None:
        """Move the finished temporary file into place, unless already there."""

    @abstractmethod
    def exists(self, sha256: bytes) -> bool: ...

    @abstractmethod
    def iter_bytes(self, sha256: bytes) -> Iterator[bytes]: ...

    @abstractmethod
    def local_file(self, sha256: bytes) -> AbstractContextManager[Path]:
        """A path to the contents, for libraries that need a real file."""

    @abstractmethod
    def delete(self, sha256: bytes) -> None: ...

    @abstractmethod
    def iter_stored(self) -> Iterator[tuple[bytes, datetime, int]]:
        """Every stored content: its SHA-256, when it was written, its size
        (for integrity checks)."""


class FilesystemStore(BlobStore):
    def __init__(self, root: Path) -> None:
        self.root = root
        super().__init__(root / "tmp")

    def path(self, sha256: bytes) -> Path:
        return self.root / "blobs" / blob_name(sha256)

    def _commit(self, tmp: Path, sha256: bytes) -> None:
        target = self.path(sha256)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp.replace(target)

    def exists(self, sha256: bytes) -> bool:
        return self.path(sha256).exists()

    def iter_bytes(self, sha256: bytes) -> Iterator[bytes]:
        with self.path(sha256).open("rb") as stream:
            while chunk := stream.read(READ_CHUNK):
                yield chunk

    @contextmanager
    def local_file(self, sha256: bytes) -> Generator[Path]:
        yield self.path(sha256)

    def delete(self, sha256: bytes) -> None:
        self.path(sha256).unlink(missing_ok=True)

    def iter_stored(self) -> Iterator[tuple[bytes, datetime, int]]:
        for path in (self.root / "blobs").glob("*/*/*"):
            if len(path.name) == 64 and path.is_file():
                try:
                    stat = path.stat()
                    written = datetime.fromtimestamp(stat.st_mtime, UTC)
                    yield bytes.fromhex(path.name), written, stat.st_size
                except (ValueError, OSError):
                    continue


class S3Store(BlobStore):
    def __init__(
        self,
        client: S3Client,
        bucket: str,
        prefix: str = "",
        temp_dir: Path | None = None,
    ) -> None:
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""
        super().__init__(temp_dir or Path(tempfile.gettempdir()) / "paperus")

    def key(self, sha256: bytes) -> str:
        return f"{self.prefix}blobs/{blob_name(sha256)}"

    def exists(self, sha256: bytes) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self.key(sha256))
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                return False
            raise
        return True

    def _commit(self, tmp: Path, sha256: bytes) -> None:
        if not self.exists(sha256):
            # Multipart for large files; the key only appears when complete.
            self.client.upload_file(str(tmp), self.bucket, self.key(sha256))

    def iter_bytes(self, sha256: bytes) -> Iterator[bytes]:
        body = self.client.get_object(Bucket=self.bucket, Key=self.key(sha256))["Body"]
        try:
            yield from body.iter_chunks(READ_CHUNK)
        finally:
            body.close()

    @contextmanager
    def local_file(self, sha256: bytes) -> Generator[Path]:
        fd, name = tempfile.mkstemp(dir=self.temp_dir)
        path = Path(name)
        try:
            with os.fdopen(fd, "wb") as out:
                for chunk in self.iter_bytes(sha256):
                    out.write(chunk)
            yield path
        finally:
            path.unlink(missing_ok=True)

    def delete(self, sha256: bytes) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self.key(sha256))

    def iter_stored(self) -> Iterator[tuple[bytes, datetime, int]]:
        pages = self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=f"{self.prefix}blobs/"
        )
        for page in pages:
            for entry in page.get("Contents", []):
                name = entry.get("Key", "").rsplit("/", 1)[-1]
                if len(name) == 64:
                    try:
                        yield bytes.fromhex(name), entry["LastModified"], entry["Size"]
                    except (ValueError, KeyError):
                        continue


def make_blob_store(settings: Settings) -> BlobStore:
    if settings.storage_backend == "s3":
        if not settings.s3_bucket:
            raise ValueError("PAPERUS_S3_BUCKET is required for the s3 backend")
        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
        )
        return S3Store(
            client, settings.s3_bucket, settings.s3_prefix, settings.temp_path
        )
    return FilesystemStore(settings.storage_path)


__all__ = [
    "BlobStore",
    "FilesystemStore",
    "S3Store",
    "StoredBlob",
    "TooLarge",
    "make_blob_store",
]
