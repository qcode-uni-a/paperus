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
import shutil
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
    """Contents in a folder (any mounted path). With ``incoming``, a local
    folder: new contents wait there while the folder is out of reach (a
    network share not mounted: its marker missing, ``MARKER``), readable
    meanwhile, and move over when it is back (``move_incoming``)."""

    def __init__(self, root: Path, incoming: Path | None = None) -> None:
        self.root = root
        self.incoming = incoming
        super().__init__((incoming or root) / "tmp")

    def reachable(self) -> bool:
        """Whether the folder is there: its marker is (an empty mount point
        is no folder of ours). Without an incoming folder, always."""
        return self.incoming is None or (self.root / MARKER).is_file()

    def path(self, sha256: bytes) -> Path:
        main = self.root / "blobs" / blob_name(sha256)
        if self.incoming is not None:
            waiting = self.incoming / "blobs" / blob_name(sha256)
            if waiting.exists():
                return waiting
        return main

    def _commit(self, tmp: Path, sha256: bytes) -> None:
        if self.exists(sha256):
            return
        folder = self.root if self.reachable() else self.incoming
        assert folder is not None
        target = folder / "blobs" / blob_name(sha256)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Across disks (the incoming folder is local): copied, then renamed.
        shutil.move(tmp, target)

    def move_incoming(self) -> int:
        """Move what waits in the incoming folder to the folder, if it is
        there; how many."""
        if self.incoming is None or not self.reachable():
            return 0
        moved = 0
        for waiting in (self.incoming / "blobs").glob("*/*/*"):
            target = self.root / "blobs" / waiting.relative_to(self.incoming / "blobs")
            if target.exists():
                waiting.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + ".partial")
            shutil.copyfile(waiting, partial)
            partial.replace(target)
            waiting.unlink()
            moved += 1
        return moved

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
        (self.root / "blobs" / blob_name(sha256)).unlink(missing_ok=True)

    def iter_stored(self) -> Iterator[tuple[bytes, datetime, int]]:
        folders = [self.root, *([self.incoming] if self.incoming else [])]
        for path in (p for folder in folders for p in (folder / "blobs").glob("*/*/*")):
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


MARKER = ".paperus-library"


def claim_if_new(blobs: BlobStore, installation: str, has_contents: bool) -> None:
    """Mark the folder as this library's when it is plainly new: it holds
    stored contents already (an installation from before markers), or the
    library has none yet. Otherwise, without its marker, it is out of reach
    (``FilesystemStore.reachable``)."""
    if not isinstance(blobs, FilesystemStore) or blobs.incoming is None:
        return
    marker = blobs.root / MARKER
    try:
        if marker.exists():
            return
        holds = any((blobs.root / "blobs").glob("*/*/*"))
        if holds or not has_contents:
            blobs.root.mkdir(parents=True, exist_ok=True)
            marker.write_text(installation + "\n")
    except OSError:
        return


def owns(blobs: BlobStore, installation: str) -> bool:
    """Whether this library may delete from the store's folder: its marker
    names this library, or there is none and this library claims it. Two
    libraries sharing a folder would each delete the other's files (those
    its own database does not know). Writing is safe either way (each
    content is written once, by its SHA-256). False if the folder cannot be
    reached."""
    if not isinstance(blobs, FilesystemStore):
        return True
    marker = blobs.root / MARKER
    try:
        return marker.read_text().strip() == installation
    except FileNotFoundError:
        try:
            blobs.root.mkdir(parents=True, exist_ok=True)
            marker.write_text(installation + "\n")
        except OSError:
            return False
        return True
    except OSError:
        return False


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
    return FilesystemStore(settings.storage_path, settings.incoming_path)


__all__ = [
    "BlobStore",
    "FilesystemStore",
    "S3Store",
    "StoredBlob",
    "TooLarge",
    "make_blob_store",
]
