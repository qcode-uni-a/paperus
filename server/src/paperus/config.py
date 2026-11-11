"""Server settings, read from environment variables prefixed with ``PAPERUS_``."""

from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAPERUS_", env_file=".env")

    database_url: str = "postgresql+psycopg://paperus:paperus@localhost:5432/paperus"
    # Reverse proxies whose X-Forwarded-For/-Proto headers are believed
    # (addresses or CIDR ranges, comma-separated); by default this machine and
    # private networks, which covers a proxy in Docker or on the local network.
    trusted_proxies: str = (
        "127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"
    )
    # Session cookies only over HTTPS (browsers also accept them on
    # http://localhost). Turn off only to test from other devices on a local
    # network over plain HTTP.
    cookie_secure: bool = True
    # The machine learning service (paperus-ml): addresses tried in order,
    # e.g. a GPU machine first and the local container as fallback.
    ml_urls: list[str] = ["http://127.0.0.1:3003"]
    ml_token: str | None = None
    ml_timeout: float = 120
    # Model for search by meaning; changing it re-embeds the library in the
    # background (keyword search keeps working meanwhile).
    embedding_model: str = "arctic-embed-m-v2"
    # Sent to metadata services (Crossref asks for one), e.g. admin@example.org.
    contact_email: str | None = None
    # File contents, stored by SHA-256: "filesystem" (any mounted path: local
    # disk, NFS, SMB) or "s3" (S3, MinIO, Ceph, …; credentials the usual AWS
    # way, e.g. AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY).
    storage_backend: Literal["filesystem", "s3"] = "filesystem"
    storage_path: Path = Path("data/files")
    incoming_path: Path | None = None
    """A local folder for new files while ``storage_path`` (a network share,
    say) is out of reach: they wait there, readable, and move over when it
    is back. Off unless set (the app's library on this computer sets it)."""
    cache_path: Path | None = None
    """A local folder keeping the files last opened from ``storage_path``
    (a network share, say), so they open while it is out of reach too. Off
    unless set."""
    cache_bytes: int = 2 * 1024**3
    """At most this much in ``cache_path``; the files opened longest ago go
    first."""
    backup_path: Path = Path("data/backups")
    """Where backups go: best another disk or a network share."""
    export_path: Path | None = None
    """Where people's exports are written (kept for a day); by default
    ``exports/`` beside the stored files, which it is not part of."""
    copy_path: Path = Path("data/library-copy")
    """Where the readable copy goes, if switched on (Administration →
    Settings → Storage template)."""
    s3_bucket: str | None = None
    s3_prefix: str = ""
    s3_endpoint_url: str | None = None
    s3_region: str | None = None
    # The built website (web/build); by default the one in this checkout.
    web_path: Path | None = Path(__file__).parents[3] / "web" / "build"
    # Temporary files for the s3 backend (uploads, text extraction).
    temp_path: Path | None = None
    max_upload_bytes: int = 512 * 1024 * 1024
    # Prometheus metrics on this port (in the container's network, not
    # through the public address); off unless set, e.g. 9464.
    metrics_port: int | None = None
    # The OIDC login's client secret (else set in Administration →
    # Settings → Authentication, stored in the database).
    oidc_client_secret: str | None = None
    # Imports from other reference managers, files included.
    max_import_bytes: int = 20 * 1024 * 1024 * 1024

    @property
    def exports_folder(self) -> Path:
        return self.export_path or self.storage_path / "exports"

    @field_validator("contact_email")
    @classmethod
    def _none_if_empty(cls, value: str | None) -> str | None:
        """Empty is unset: compose passes an empty ``CONTACT_EMAIL`` as ""."""
        return (value or "").strip() or None
