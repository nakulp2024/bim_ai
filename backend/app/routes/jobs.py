"""Progress polling for background jobs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..jobs import get_job_manager

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}")
def get_job(job_id: str) -> dict:
    job = get_job_manager().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
    return job
