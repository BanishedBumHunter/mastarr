"""Settings, layered env > YAML > defaults.

The YAML file exists so a whole Mastarr install can be version-controlled and reproduced.
Secrets are deliberately env-only in practice: `config.yml` supports an `api_key` field for
completeness, but the documented pattern is `api_key_env` pointing at an env var name so the
committed YAML stays free of credentials.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceConfig(BaseModel):
    """One declaratively-configured *arr service."""

    name: str
    type: str
    url: str
    api_key: str | None = None
    api_key_env: str | None = None
    enabled: bool = True

    def resolve_api_key(self) -> str | None:
        """Env var reference wins over an inline key, so YAML can stay credential-free."""
        if self.api_key_env:
            return os.environ.get(self.api_key_env) or None
        return self.api_key or None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MASTARR_", env_file=".env", extra="ignore"
    )

    data_dir: Path = Path("/data")
    config_file: Path | None = None

    # Fernet key for API-key encryption at rest. Generated and persisted on first run
    # when unset — see crypto.load_or_create_key.
    secret_key: str | None = None

    # Signing key for session JWTs. Distinct from secret_key so rotating a session
    # secret never risks making stored API keys unreadable.
    jwt_secret: str | None = None
    session_hours: int = 12

    http_timeout: float = 10.0
    dashboard_cache_seconds: float = 5.0

    # Hosts auto-discovery probes when no explicit target is given.
    discovery_hosts: list[str] = Field(default_factory=list)

    log_level: str = "INFO"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "mastarr.db"

    def load_services(self) -> list[ServiceConfig]:
        """Services declared in the YAML config file, if one is configured."""
        if not self.config_file:
            return []
        path = Path(self.config_file)
        if not path.is_file():
            return []
        raw: Any = yaml.safe_load(path.read_text()) or {}
        return [ServiceConfig(**item) for item in raw.get("services", [])]

    def yaml_overrides(self) -> dict[str, Any]:
        """Non-service top-level keys from the YAML file."""
        if not self.config_file:
            return {}
        path = Path(self.config_file)
        if not path.is_file():
            return {}
        raw: Any = yaml.safe_load(path.read_text()) or {}
        return {k: v for k, v in raw.items() if k != "services"}


@lru_cache
def get_settings() -> Settings:
    """Settings singleton. env wins; YAML fills the gaps it leaves."""
    settings = Settings()
    overrides = settings.yaml_overrides()
    if overrides:
        explicit = set(settings.model_fields_set)
        merged = {
            **{k: v for k, v in overrides.items() if k not in explicit},
            **settings.model_dump(include=explicit),
        }
        settings = Settings(**merged)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
