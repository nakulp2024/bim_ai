"""Job-state pub/sub between Celery workers (sync) and SSE handlers (async)."""
from __future__ import annotations

import json
from typing import Any

import redis as sync_redis
import redis.asyncio as async_redis_module

from .config import settings

_sync_pool = sync_redis.ConnectionPool.from_url(settings.redis_url)


def channel_for(job_id: str) -> str:
    return f"job:{job_id}"


def publish_job(job_id: str, payload: dict[str, Any]) -> None:
    """Best-effort publish; never raises into the caller."""
    try:
        r = sync_redis.Redis(connection_pool=_sync_pool)
        r.publish(channel_for(job_id), json.dumps(payload, default=str))
    except Exception:
        pass


def async_client() -> async_redis_module.Redis:
    return async_redis_module.from_url(settings.redis_url, decode_responses=True)
