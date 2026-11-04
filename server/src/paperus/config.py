"""Server settings, read from environment variables prefixed with ``PAPERUS_``."""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAPERUS_", env_file=".env")

    database_url: str = "postgresql+psycopg://paperus:paperus@localhost:5432/paperus"
    # Sent to metadata services (Crossref asks for one), e.g. admin@example.org.
    contact_email: str | None = None
    # File contents, stored by SHA-256: "filesystem" (any mounted path: local
    # disk, NFS, SMB) or "s3" (S3, MinIO, Ceph, …; credentials the usual AWS
    # way, e.g. AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY).
    storage_backend: Literal["filesystem", "s3"] = "filesystem"
    storage_path: Path = Path("data/files")
    s3_bucket: str | None = None
    s3_prefix: str = ""
    s3_endpoint_url: str | None = None
    s3_region: str | None = None
    # The built website (web/build); by default the one in this checkout.
    web_path: Path | None = Path(__file__).parents[3] / "web" / "build"
    # Temporary files for the s3 backend (uploads, text extraction).
    temp_path: Path | None = None
    max_upload_bytes: int = 512 * 1024 * 1024
