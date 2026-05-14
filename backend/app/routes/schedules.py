from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.jwt_tokens import current_user
from ..celery_app import celery
from ..config import settings
from ..db import Job, MappingProposal, ScheduleUpload, User, get_session
from ..schedules.ingest import read_schedule, summarise

router = APIRouter(prefix="/schedules", tags=["schedules"])

_ALLOWED_EXT = {".csv", ".xlsx", ".xls"}


def _data_root() -> Path:
    root = Path(settings.data_dir) / "schedules"
    root.mkdir(parents=True, exist_ok=True)
    return root


async def _resolve_referenced_object(
    user: User, project_id: str, model_id: str, version_id: str
) -> str | None:
    """Look up the version's referencedObject hash via Speckle GraphQL."""
    async with httpx.AsyncClient(timeout=15) as http:
        resp = await http.post(
            f"{settings.speckle_internal_url}/graphql",
            headers={"authorization": f"Bearer {user.speckle_access_token}"},
            json={
                "query": (
                    "query($pid:String!,$mid:String!,$vid:String!){"
                    "project(id:$pid){model(id:$mid){version(id:$vid){referencedObject}}}}"
                ),
                "variables": {"pid": project_id, "mid": model_id, "vid": version_id},
            },
        )
    if resp.status_code != 200:
        return None
    data = resp.json().get("data") or {}
    try:
        return data["project"]["model"]["version"]["referencedObject"]
    except (TypeError, KeyError):
        return None


@router.post("")
async def upload_schedule(
    speckle_project_id: str = Form(...),
    speckle_model_id: str = Form(...),
    speckle_version_id: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(400, detail="missing filename")
    ext = Path(file.filename).suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(400, detail=f"unsupported file type: {ext}")

    schedule_id = uuid.uuid4().hex
    target = _data_root() / f"{schedule_id}{ext}"
    sha = hashlib.sha256()
    with target.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            sha.update(chunk)
            out.write(chunk)

    try:
        df = read_schedule(target)
    except Exception as e:
        target.unlink(missing_ok=True)
        raise HTTPException(400, detail=f"failed to parse schedule: {e}") from e

    summary = summarise(df, sample_n=5)
    referenced_object = await _resolve_referenced_object(
        user, speckle_project_id, speckle_model_id, speckle_version_id
    )

    schedule = ScheduleUpload(
        id=schedule_id,
        user_id=user.id,
        speckle_project_id=speckle_project_id,
        speckle_model_id=speckle_model_id,
        speckle_version_id=speckle_version_id,
        speckle_referenced_object=referenced_object,
        filename=file.filename,
        content_sha256=sha.hexdigest(),
        storage_path=str(target),
        headers=summary["headers"],
        sample_rows=summary["sample_rows"],
        row_count=summary["row_count"],
    )
    session.add(schedule)

    job = Job(
        id=uuid.uuid4().hex,
        user_id=user.id,
        kind="ai_map_columns",
        state="queued",
        progress=0.0,
        message="Queued.",
        payload={"schedule_id": schedule_id},
    )
    session.add(job)
    await session.commit()

    celery.send_task("app.tasks.map_columns.run", args=[job.id, schedule.id])

    return {
        "schedule_id": schedule.id,
        "job_id": job.id,
        "row_count": summary["row_count"],
        "headers": summary["headers"],
    }


@router.get("")
async def list_schedules(
    speckle_version_id: str | None = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    stmt = (
        select(ScheduleUpload)
        .where(ScheduleUpload.user_id == user.id)
        .order_by(desc(ScheduleUpload.created_at))
    )
    if speckle_version_id:
        stmt = stmt.where(ScheduleUpload.speckle_version_id == speckle_version_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "filename": r.filename,
            "row_count": r.row_count,
            "headers": r.headers,
            "speckle_project_id": r.speckle_project_id,
            "speckle_model_id": r.speckle_model_id,
            "speckle_version_id": r.speckle_version_id,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/{schedule_id}/mapping")
async def get_mapping(
    schedule_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    sched = (
        await session.execute(
            select(ScheduleUpload).where(
                ScheduleUpload.id == schedule_id, ScheduleUpload.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if not sched:
        raise HTTPException(404, detail="schedule not found")
    proposal = (
        await session.execute(
            select(MappingProposal)
            .where(MappingProposal.schedule_id == schedule_id)
            .order_by(desc(MappingProposal.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if not proposal:
        return {"schedule_id": schedule_id, "proposal": None}
    return {
        "schedule_id": schedule_id,
        "proposal_id": proposal.id,
        "proposed": proposal.proposed,
        "join_strategy": proposal.join_strategy,
        "confidence": proposal.confidence,
        "rationale": proposal.rationale,
        "confirmed": proposal.confirmed,
        "confirmed_at": proposal.confirmed_at.isoformat() if proposal.confirmed_at else None,
        "headers": sched.headers,
        "sample_rows": sched.sample_rows,
        "catalog_summary": {
            "total_elements": proposal.catalog_summary.get("total_elements"),
            "by_category": proposal.catalog_summary.get("by_category"),
            "by_level": proposal.catalog_summary.get("by_level"),
        },
    }


@router.post("/{schedule_id}/mapping/confirm")
async def confirm_mapping(
    schedule_id: str,
    payload: dict[str, Any],
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    sched = (
        await session.execute(
            select(ScheduleUpload).where(
                ScheduleUpload.id == schedule_id, ScheduleUpload.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if not sched:
        raise HTTPException(404, detail="schedule not found")
    proposal = (
        await session.execute(
            select(MappingProposal)
            .where(MappingProposal.schedule_id == schedule_id)
            .order_by(desc(MappingProposal.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if not proposal:
        raise HTTPException(409, detail="no proposal yet; wait for the job to finish")

    proposal.confirmed = payload
    proposal.confirmed_at = datetime.now(timezone.utc)
    await session.commit()
    return {"ok": True, "proposal_id": proposal.id}
