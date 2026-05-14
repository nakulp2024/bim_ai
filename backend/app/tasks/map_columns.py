from __future__ import annotations

import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..ai.mapping import propose_mapping
from ..celery_app import celery
from ..db_sync import SyncSessionLocal
from ..db import Job, MappingProposal, ScheduleUpload, User
from ..schedules.ingest import read_schedule, summarise
from ..speckle.catalog import build_catalog_summary


def _update_job(session, job: Job, **fields) -> None:
    for k, v in fields.items():
        setattr(job, k, v)
    job.updated_at = datetime.now(timezone.utc)
    session.add(job)
    session.commit()


@celery.task(name="app.tasks.map_columns.run", bind=True)
def run(self, job_id: str, schedule_id: str) -> dict:
    with SyncSessionLocal() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one()
        try:
            _update_job(session, job, state="running", progress=0.05, message="Loading schedule…")

            schedule = session.execute(
                select(ScheduleUpload).where(ScheduleUpload.id == schedule_id)
            ).scalar_one()
            user = session.execute(
                select(User).where(User.id == schedule.user_id)
            ).scalar_one()

            df = read_schedule(Path(schedule.storage_path))
            summary = summarise(df, sample_n=5)

            _update_job(session, job, progress=0.25, message="Fetching Speckle catalog…")
            catalog = build_catalog_summary(
                token=user.speckle_access_token,
                speckle_project_id=schedule.speckle_project_id,
                referenced_object=schedule.speckle_referenced_object or schedule.speckle_version_id,
            )

            _update_job(session, job, progress=0.6, message="Asking Claude for column mapping…")
            proposal = propose_mapping(
                headers=summary["headers"],
                sample_rows=summary["sample_rows"],
                catalog_summary=catalog,
            )

            mp = MappingProposal(
                id=uuid.uuid4().hex,
                schedule_id=schedule.id,
                proposed=proposal.model_dump(),
                join_strategy=proposal.join_strategy,
                confidence=proposal.confidence,
                rationale=proposal.rationale,
                catalog_summary=catalog,
            )
            session.add(mp)
            session.commit()

            _update_job(
                session,
                job,
                state="ready",
                progress=1.0,
                message="Mapping proposal ready.",
                result={
                    "schedule_id": schedule.id,
                    "mapping_proposal_id": mp.id,
                    "confidence": proposal.confidence,
                    "join_strategy": proposal.join_strategy,
                },
            )
            return job.result or {}
        except Exception as e:  # noqa: BLE001
            _update_job(
                session,
                job,
                state="failed",
                error=f"{type(e).__name__}: {e}\n{traceback.format_exc()[:4000]}",
                message="Job failed; see error.",
            )
            raise
