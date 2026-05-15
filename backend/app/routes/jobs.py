from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.jwt_tokens import current_user, decode_jwt
from ..db import Job, User, get_session, SessionLocal
from ..events import async_client, channel_for

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _job_to_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "kind": job.kind,
        "state": job.state,
        "progress": job.progress,
        "message": job.message,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    job = (
        await session.execute(
            select(Job).where(Job.id == job_id, Job.user_id == user.id)
        )
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(404, detail="job not found")
    return _job_to_dict(job)


@router.get("/{job_id}/events")
async def stream_job_events(
    job_id: str,
    token: str = Query(..., description="App JWT (EventSource can't send headers)"),
) -> StreamingResponse:
    """SSE stream of job state changes.

    Auth: takes the app JWT as a query parameter because the browser's
    EventSource API doesn't support custom headers.
    """
    payload = decode_jwt(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(401, detail="malformed token")

    async def gen() -> AsyncIterator[bytes]:
        # Emit current state first so late subscribers don't hang.
        async with SessionLocal() as session:
            job = (
                await session.execute(
                    select(Job).where(Job.id == job_id, Job.user_id == user_id)
                )
            ).scalar_one_or_none()
            if not job:
                yield b"event: error\ndata: not found\n\n"
                return
            yield f"data: {json.dumps(_job_to_dict(job))}\n\n".encode()
            if job.state in {"ready", "failed"}:
                return

        client = async_client()
        sub = client.pubsub()
        await sub.subscribe(channel_for(job_id))
        last_keepalive = asyncio.get_event_loop().time()
        try:
            while True:
                msg = await sub.get_message(ignore_subscribe_messages=True, timeout=15.0)
                if msg is None:
                    # Heartbeat keeps proxies / browsers from closing the connection.
                    yield b": keepalive\n\n"
                    last_keepalive = asyncio.get_event_loop().time()
                    continue
                data = msg.get("data")
                if isinstance(data, (bytes, bytearray)):
                    data = data.decode()
                if not isinstance(data, str):
                    continue
                yield f"data: {data}\n\n".encode()
                try:
                    parsed = json.loads(data)
                except Exception:
                    parsed = {}
                if parsed.get("state") in {"ready", "failed"}:
                    return
                _ = last_keepalive  # silence linter
        finally:
            try:
                await sub.unsubscribe(channel_for(job_id))
                await sub.aclose()
            except Exception:
                pass
            try:
                await client.aclose()
            except Exception:
                pass

    return StreamingResponse(gen(), media_type="text/event-stream")
