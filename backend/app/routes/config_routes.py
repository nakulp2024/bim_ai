"""Read-only view of the active config files, for the UI and for debugging."""

from __future__ import annotations

from fastapi import APIRouter

from ..config import CONFIG_NAMES, get_settings, load_config
from ..schedule.lod import LEVEL_INFO, LEVELS

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
def get_all_config() -> dict:
    settings = get_settings()
    return {
        "config_dir": str(settings.config_dir),
        "llm_enabled": settings.llm_enabled,
        "files": {name: load_config(name) for name in CONFIG_NAMES},
    }


@router.get("/levels")
def get_levels() -> dict:
    return {
        "levels": [
            {"level": level, **LEVEL_INFO[level], "is_default": level == "L3"} for level in LEVELS
        ]
    }
