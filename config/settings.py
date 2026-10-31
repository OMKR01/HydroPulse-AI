"""Configuration module for HydroPulse AI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    """Application runtime settings loaded from environment or defaults."""

    app_name: str = "HydroPulse AI"
    app_version: str = "0.1.0"
    environment: str = os.getenv("FLASK_ENV", "development")
    debug: bool = os.getenv("FLASK_DEBUG", "1") in ("1", "true", "True")
    secret_key: str = os.getenv("SECRET_KEY", "dev-secret-hydropulse-2026")
    port: int = int(os.getenv("PORT", "5000"))
    host: str = os.getenv("HOST", "0.0.0.0")

    database_url: str = os.getenv(
        "DATABASE_URL", f"sqlite:///{DATA_DIR / 'interim' / 'hydropulse.db'}"
    )
    openmeteo_timeout_seconds: int = int(os.getenv("OPENMETEO_TIMEOUT_SECONDS", "15"))
    requests_cache_expire_after: int = int(os.getenv("REQUESTS_CACHE_EXPIRE_AFTER", "21600"))

    class Config:
        env_file = ".env"
        extra = "ignore"


def load_stations_config(config_path: Path | None = None) -> list[dict[str, Any]]:
    """Load monitoring stations configuration from YAML."""
    path = config_path or (CONFIG_DIR / "stations.yaml")
    if not path.exists():
        raise FileNotFoundError(f"Stations configuration not found at {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("stations", [])


def load_thresholds_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load flood, drought, and water quality thresholds from YAML."""
    path = config_path or (CONFIG_DIR / "thresholds.yaml")
    if not path.exists():
        raise FileNotFoundError(f"Thresholds configuration not found at {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


settings = Settings()
