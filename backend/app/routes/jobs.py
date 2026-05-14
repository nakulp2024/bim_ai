from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.jwt_tokens import current_user
from ..db import Job, User, get_session

router = APIRouter(prefix="/jobs", tags=["jobs"])


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
