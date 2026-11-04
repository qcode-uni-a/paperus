"""Server settings, read from environment variables prefixed with ``PAPERUS_``."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAPERUS_", env_file=".env")

    database_url: str = "postgresql+psycopg://paperus:paperus@localhost:5432/paperus"
