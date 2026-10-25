"""Runtime settings, read from environment variables (never hard-code secrets)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _split(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./agentval.db")
    )
    cors_origins: list[str] = field(
        default_factory=lambda: _split(
            os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
        )
    )
    seed_on_startup: bool = field(
        default_factory=lambda: os.getenv("AGENTVAL_SEED", "false").lower() in {"1", "true", "yes"}
    )


def get_settings() -> Settings:
    return Settings()
