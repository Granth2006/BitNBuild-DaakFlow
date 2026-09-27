"""Application settings, loaded from environment / backend/.env.

Secrets (the Neon connection strings) live only in `.env`, which is
git-ignored. Nothing here hardcodes a credential.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Neon Postgres. Pooled is preferred for the app runtime.
    database_url: Optional[str] = None
    database_url_pooled: Optional[str] = None

    # Optional real road-distance provider; blank => offline haversine fallback.
    osrm_url: Optional[str] = None

    port: int = 8000

    # Comma-separated browser origins allowed for CORS + Socket.IO. Defaults to
    # the local dev frontend; override in production via the CORS_ORIGINS env
    # var, e.g. "https://daakflow.vercel.app,https://www.daakflow.app". Because
    # the API sends credentials, "*" is not usable here — list explicit origins.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        """Parsed allow-list of browser origins (CORS middleware + Socket.IO)."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sqlalchemy_url(self) -> Optional[str]:
        """The DB URL adapted to the psycopg (v3) driver, or None if unset."""
        raw = self.database_url_pooled or self.database_url
        if not raw:
            return None
        raw = raw.strip()
        if raw.startswith("postgresql+"):
            return raw
        if raw.startswith("postgresql://"):
            return "postgresql+psycopg://" + raw[len("postgresql://") :]
        if raw.startswith("postgres://"):
            return "postgresql+psycopg://" + raw[len("postgres://") :]
        return raw


settings = Settings()
