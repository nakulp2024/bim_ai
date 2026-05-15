"""Build an AnimationScript from the resolved schedule + AI-grouped phases."""
from __future__ import annotations

import math
import traceback
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select

from ..ai.animation import propose_phases
from ..celery_app import celery
from ..db import (
    Animation,
    Job,
    MappingProposal,
    ScheduleElementLink,
    ScheduleUpload,
)
from ..db_sync import SyncSessionLocal
from ..events import publish_job
from ..schedules.ingest import read_schedule


def _update_job(session, job: Job, **fields) -> None:
    for k, v in fields.items():
        setattr(job, k, v)
    job.updated_at = datetime.now(timezone.utc)
    session.add(job)
    session.commit()
    publish_job(
        job.id,
        {
            "id": job.id,
            "state": job.state,
            "progress": job.progress,
            "message": job.message,
            "result": job.result,
            "error": job.error,
        },
    )


def _role_to_column(mapping: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in mapping:
        role = m.get("role")
        col = m.get("column")
        if role and col and role != "ignored":
            out.setdefault(role, col)
    return out


def _parse_date(v: Any) -> date | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    try:
        ts = pd.to_datetime(v, errors="coerce")
    except Exception:
        return None
    if ts is None or pd.isna(ts):
        return None
    return ts.date()


def _build_tasks(
    df: pd.DataFrame,
    role_col: dict[str, str],
    linked_task_ids: set[str],
) -> tuple[list[dict[str, Any]], date]:
    task_col = role_col.get("task_id")
    name_col = role_col.get("name")
    start_col = role_col.get("start")
    end_col = role_col.get("end")
    activity_col = role_col.get("activity")
    phase_col = role_col.get("phase")
    wbs_col = role_col.get("wbs")

    if not start_col or not end_col:
        raise RuntimeError(
            "Mapping is missing start and/or end columns; cannot build a timeline."
        )

    parsed_rows: list[dict[str, Any]] = []
    for i, row in df.iterrows():
        s = _parse_date(row.get(start_col))
        e = _parse_date(row.get(end_col))
        if not s or not e:
            continue
        if e < s:
            s, e = e, s
        tid = (
            str(row[task_col]).strip()
            if task_col and task_col in df.columns and pd.notna(row.get(task_col))
            else f"row-{i}"
        )
        if tid not in linked_task_ids:
            continue
        parsed_rows.append(
            {
                "task_id": tid,
                "name": str(row.get(name_col, "") or "") if name_col else None,
                "start_date": s,
                "end_date": e,
                "activity": (
                    str(row.get(activity_col, "construct") or "construct")
                    if activity_col
                    else "construct"
                ).lower(),
                "phase_hint": (
                    str(row.get(phase_col, "") or "") if phase_col else None
                ),
                "wbs": str(row.get(wbs_col, "") or "") if wbs_col else None,
            }
        )

    if not parsed_rows:
        raise RuntimeError(
            "No schedule rows had both a parseable start/end date AND a "
            "resolved Speckle element. Re-check the mapping."
        )

    project_start = min(r["start_date"] for r in parsed_rows)
    tasks: list[dict[str, Any]] = []
    for r in parsed_rows:
        tasks.append(
            {
                "task_id": r["task_id"],
                "name": r["name"],
                "start_day": (r["start_date"] - project_start).days,
                "end_day": (r["end_date"] - project_start).days,
                "activity": r["activity"],
                "phase": r["phase_hint"] or None,
                "wbs": r["wbs"] or None,
            }
        )
    return tasks, project_start


@celery.task(name="app.tasks.generate_animation.run", bind=True)
def run(self, job_id: str, schedule_id: str) -> dict:
    with SyncSessionLocal() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one()
        try:
            _update_job(session, job, state="running", progress=0.05, message="Loading schedule…")

            schedule = session.execute(
                select(ScheduleUpload).where(ScheduleUpload.id == schedule_id)
            ).scalar_one()
            proposal = session.execute(
                select(MappingProposal)
                .where(MappingProposal.schedule_id == schedule_id)
                .order_by(MappingProposal.created_at.desc())
                .limit(1)
            ).scalar_one()
            confirmed = proposal.confirmed or proposal.proposed
            mapping_entries = confirmed.get("mapping", [])
            role_col = _role_to_column(mapping_entries)

            linked_task_ids = {
                tid for (tid,) in session.execute(
                    select(ScheduleElementLink.task_id)
                    .where(ScheduleElementLink.schedule_id == schedule_id)
                    .distinct()
                )
            }
            if not linked_task_ids:
                raise RuntimeError("No resolved element links; can't animate.")

            df = read_schedule(Path(schedule.storage_path))

            _update_job(session, job, progress=0.25, message="Computing task timing…")
            tasks, project_start = _build_tasks(df, role_col, linked_task_ids)

            _update_job(session, job, progress=0.55, message="Asking Claude for phase grouping…")
            grouping = propose_phases(tasks)

            # Make sure every task ends up in some phase.
            covered = {t for ph in grouping.phases for t in ph.task_ids}
            missing = [t["task_id"] for t in tasks if t["task_id"] not in covered]
            phases = [p.model_dump() for p in grouping.phases]
            if missing:
                phases.append(
                    {"name": "Other", "color_hex": "#888888", "task_ids": missing}
                )

            duration_days = max((t["end_day"] for t in tasks), default=0) + 1
            script = {
                "version": "1.0",
                "start_date": project_start.isoformat(),
                "duration_days": duration_days,
                "tasks": tasks,
                "phases": phases,
            }

            anim = Animation(id=uuid.uuid4().hex, schedule_id=schedule.id, script=script)
            session.add(anim)
            session.commit()

            _update_job(
                session,
                job,
                state="ready",
                progress=1.0,
                message=f"Animation ready ({len(tasks)} tasks, {duration_days} days).",
                result={
                    "animation_id": anim.id,
                    "schedule_id": schedule.id,
                    "task_count": len(tasks),
                    "duration_days": duration_days,
                    "phase_count": len(phases),
                },
            )
            return job.result or {}
        except Exception as e:  # noqa: BLE001
            _update_job(
                session,
                job,
                state="failed",
                error=f"{type(e).__name__}: {e}\n{traceback.format_exc()[:4000]}",
                message="Animation generation failed.",
            )
            raise
