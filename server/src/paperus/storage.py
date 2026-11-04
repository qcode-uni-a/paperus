"""Content-addressed storage for file contents (blobs) on the filesystem."""

import hashlib
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


class TooLarge(ValueError):
    pass


@dataclass(frozen=True)
class StoredBlob:
    sha256: bytes
    size: int
    head: bytes
    """The first bytes, for checking the file type."""


class BlobStore:
    """Stores each content once under its SHA-256: ``blobs/ab/cd/abcd…``."""

    HEAD_SIZE = 1024

    def __init__(self, root: Path) -> None:
        self.root = root
        self._tmp = root / "tmp"
        self._tmp.mkdir(parents=True, exist_ok=True)

    def path(self, sha256: bytes) -> Path:
        name = sha256.hex()
        return self.root / "blobs" / name[:2] / name[2:4] / name

    def put(self, chunks: Iterable[bytes], *, max_size: int) -> StoredBlob:
        """Write the chunks, hashing on the way; keep an existing copy if present."""
        digest = hashlib.sha256()
        size = 0
        head = b""
        fd, tmp_name = tempfile.mkstemp(dir=self._tmp)
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
            target = self.path(sha256)
            if target.exists():
                tmp.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp.replace(target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return StoredBlob(sha256=sha256, size=size, head=head)
