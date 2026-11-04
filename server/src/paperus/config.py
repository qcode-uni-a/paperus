"""Server settings, read from environment variables prefixed with ``PAPERUS_``."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAPERUS_", env_file=".env")

    database_url: str = "postgresql+psycopg://paperus:paperus@localhost:5432/paperus"
    # Sent to metadata services (Crossref asks for one), e.g. admin@example.org.
    contact_email: str | None = None
    # File contents, stored by SHA-256.
    storage_path: Path = Path("data/files")
    max_upload_bytes: int = 512 * 1024 * 1024
