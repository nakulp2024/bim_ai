"""Application settings and YAML config loading.

Config files live in ``backend/config`` by default. Point ``IFCSCHED_CONFIG_DIR``
at another directory to override any of them; files missing from the override
directory fall back to the packaged defaults.
"""

from __future__ import annotations

import os
from copy import deepcopy
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

import yaml

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = BACKEND_ROOT / "config"

CONFIG_NAMES = ("filters", "work_packages", "rates", "sequencing")


class Settings:
    """Runtime settings, all overridable through environment variables."""

    def __init__(self) -> None:
        self.config_dir = Path(os.getenv("IFCSCHED_CONFIG_DIR", DEFAULT_CONFIG_DIR))
        self.data_dir = Path(os.getenv("IFCSCHED_DATA_DIR", BACKEND_ROOT.parent / "data"))
        self.database_url = os.getenv(
            "IFCSCHED_DATABASE_URL", f"sqlite:///{self.data_dir / 'ifcsched.db'}"
        )
        self.max_upload_mb = int(os.getenv("IFCSCHED_MAX_UPLOAD_MB", "1024"))
        self.cors_origins = [
            o.strip()
            for o in os.getenv("IFCSCHED_CORS_ORIGINS", "http://localhost:5173").split(",")
            if o.strip()
        ]
        # Deriving geometry for a 100k-entity model is slow; cap how many
        # elements we are willing to fall back to ifcopenshell.geom for.
        self.max_derived_geometry = int(os.getenv("IFCSCHED_MAX_DERIVED_GEOMETRY", "20000"))
        self.llm_enabled = os.getenv("IFCSCHED_LLM_ENABLED", "false").lower() == "true"
        self.llm_model = os.getenv("IFCSCHED_LLM_MODEL", "claude-sonnet-5")
        self.llm_api_key = os.getenv("ANTHROPIC_API_KEY", "")

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def project_dir(self) -> Path:
        return self.data_dir / "projects"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.upload_dir, self.project_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    return loaded or {}


@cache
def _load_config_cached(name: str, config_dir: str) -> dict[str, Any]:
    if name not in CONFIG_NAMES:
        raise KeyError(f"unknown config file: {name}")
    data = _read_yaml(DEFAULT_CONFIG_DIR / f"{name}.yaml")
    override_dir = Path(config_dir)
    if override_dir != DEFAULT_CONFIG_DIR:
        data.update(_read_yaml(override_dir / f"{name}.yaml"))
    return data


def load_config(name: str, config_dir: Path | None = None) -> dict[str, Any]:
    """Return a deep copy of a config file so callers can mutate it freely."""
    directory = config_dir or get_settings().config_dir
    return deepcopy(_load_config_cached(name, str(directory)))


def clear_config_cache() -> None:
    _load_config_cached.cache_clear()
