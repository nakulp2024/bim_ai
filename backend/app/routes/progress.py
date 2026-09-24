"""Baselines, the data date, and progress reporting."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, update

from ..db import BaselineRecord, ProgressUpdate, Project, ScheduleRecord, session_scope
from ..schedule.calendar import WorkCalendar
from ..schedule.progress import evaluate_progress, snapshot_baseline
from ..schemas import BaselineCreate, DataDateUpdate, ProgressReport

router = APIRouter(prefix="/api/projects", tags=["progress"])

# Fields a report may leave blank; a blank never wipes out an earlier value.
MERGED_FIELDS = ("percent_complete", "quantity_placed", "actual_start", "actual_finish", "note")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _parse_date(value: str | None, field: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"{field} must be YYYY-MM-DD, got {value!r}"
        ) from exc


def _require_project(session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found.")
    return project


def _require_schedule(session, project_id: int) -> ScheduleRecord:
    record = session.query(ScheduleRecord).filter_by(project_id=project_id).one_or_none()
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"No schedule generated for project {project_id}."
        )
    return record


def _calendar(record: ScheduleRecord) -> WorkCalendar:
    stored = record.calendar or {}
    return WorkCalendar(
        start_date=stored.get("start_date"),
        work_days=stored.get("work_days"),
        holidays=stored.get("holidays"),
    )


def _effective_data_date(project: Project) -> date:
    return project.data_date or date.today()


def merge_updates(updates: list[ProgressUpdate]) -> dict[str, dict[str, Any]]:
    """Fold a task's reports, oldest first, into its current state.

    Field reporting is partial: "started today" one day, "68 m3 placed" a week
    later. Each later non-blank value overrides an earlier one; a blank never
    erases what was already reported.
    """
    ordered = sorted(updates, key=lambda u: (u.reported_on, u.id))
    state: dict[str, dict[str, Any]] = {}
    for update_row in ordered:
        current = state.setdefault(update_row.task_id, {"task_id": update_row.task_id})
        row = update_row.as_dict()
        for field in MERGED_FIELDS:
            if row[field] not in (None, ""):
                current[field] = row[field]
        current["reported_on"] = row["reported_on"]
    return state


def _current_baseline(session, project_id: int) -> BaselineRecord | None:
    return session.scalars(
        select(BaselineRecord)
        .where(BaselineRecord.project_id == project_id, BaselineRecord.is_current.is_(True))
        .order_by(BaselineRecord.id.desc())
    ).first()


def evaluate(session, project_id: int) -> dict[str, Any]:
    """The full progress view: tasks with state and variance, plus a summary."""
    project = _require_project(session, project_id)
    record = _require_schedule(session, project_id)
    updates = session.scalars(
        select(ProgressUpdate).where(ProgressUpdate.project_id == project_id)
    ).all()
    baseline = _current_baseline(session, project_id)

    result = evaluate_progress(
        tasks=list(record.tasks or []),
        links=list(record.links or []),
        calendar=_calendar(record),
        data_date=_effective_data_date(project),
        progress=merge_updates(list(updates)),
        baseline=(baseline.tasks if baseline else None),
    )
    payload = result.as_dict()
    payload["baseline"] = baseline.as_dict() if baseline else None
    payload["data_date_is_default"] = project.data_date is None
    return payload


# --------------------------------------------------------------------------
# data date
# --------------------------------------------------------------------------


@router.put("/{project_id}/data-date")
def set_data_date(project_id: int, payload: DataDateUpdate) -> dict:
    parsed = _parse_date(payload.data_date, "data_date")
    with session_scope() as session:
        project = _require_project(session, project_id)
        project.data_date = parsed
        return {"data_date": parsed.isoformat() if parsed else None}


# --------------------------------------------------------------------------
# baselines
# --------------------------------------------------------------------------


@router.get("/{project_id}/baselines")
def list_baselines(project_id: int) -> dict:
    with session_scope() as session:
        _require_project(session, project_id)
        rows = session.scalars(
            select(BaselineRecord)
            .where(BaselineRecord.project_id == project_id)
            .order_by(BaselineRecord.id.desc())
        ).all()
        return {"baselines": [row.as_dict() for row in rows]}


@router.post("/{project_id}/baselines")
def create_baseline(project_id: int, payload: BaselineCreate) -> dict:
    """Freeze the current plan. The new baseline becomes the current one."""
    with session_scope() as session:
        _require_project(session, project_id)
        record = _require_schedule(session, project_id)
        tasks = snapshot_baseline(list(record.tasks or []))
        if not tasks:
            raise HTTPException(status_code=409, detail="The schedule has no tasks to baseline.")

        count = session.query(BaselineRecord).filter_by(project_id=project_id).count()
        session.execute(
            update(BaselineRecord)
            .where(BaselineRecord.project_id == project_id)
            .values(is_current=False)
        )
        finishes = [task["finish_date"] for task in tasks if task.get("finish_date")]
        baseline = BaselineRecord(
            project_id=project_id,
            name=(payload.name or "").strip() or f"Baseline {count + 1}",
            is_current=True,
            tasks=tasks,
            task_count=len(tasks),
            finish_date=max(finishes) if finishes else None,
        )
        session.add(baseline)
        session.flush()
        return baseline.as_dict()


@router.post("/{project_id}/baselines/{baseline_id}/activate")
def activate_baseline(project_id: int, baseline_id: int) -> dict:
    with session_scope() as session:
        baseline = session.get(BaselineRecord, baseline_id)
        if baseline is None or baseline.project_id != project_id:
            raise HTTPException(status_code=404, detail=f"Baseline {baseline_id} not found.")
        session.execute(
            update(BaselineRecord)
            .where(BaselineRecord.project_id == project_id)
            .values(is_current=False)
        )
        baseline.is_current = True
        return baseline.as_dict()


@router.delete("/{project_id}/baselines/{baseline_id}")
def delete_baseline(project_id: int, baseline_id: int) -> dict:
    with session_scope() as session:
        baseline = session.get(BaselineRecord, baseline_id)
        if baseline is None or baseline.project_id != project_id:
            raise HTTPException(status_code=404, detail=f"Baseline {baseline_id} not found.")
        was_current = bool(baseline.is_current)
        session.delete(baseline)
        session.flush()
        if was_current:
            # Fall back to the newest remaining baseline rather than none.
            newest = session.scalars(
                select(BaselineRecord)
                .where(BaselineRecord.project_id == project_id)
                .order_by(BaselineRecord.id.desc())
            ).first()
            if newest is not None:
                newest.is_current = True
        return {"deleted": baseline_id}


# --------------------------------------------------------------------------
# progress
# --------------------------------------------------------------------------


@router.get("/{project_id}/progress")
def get_progress(project_id: int) -> dict:
    with session_scope() as session:
        return evaluate(session, project_id)


@router.post("/{project_id}/progress")
def report_progress(project_id: int, payload: ProgressReport) -> dict:
    """Record a batch of task updates and return the recalculated view."""
    with session_scope() as session:
        project = _require_project(session, project_id)
        record = _require_schedule(session, project_id)
        data_date = _effective_data_date(project)
        reported_on = _parse_date(payload.reported_on, "reported_on") or data_date

        known = {task.get("id") for task in record.tasks or []}
        unknown = sorted({entry.task_id for entry in payload.entries} - known)
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown task id(s): {', '.join(unknown[:10])}"
                + (f" and {len(unknown) - 10} more" if len(unknown) > 10 else ""),
            )

        for entry in payload.entries:
            actual_start = _parse_date(entry.actual_start, "actual_start")
            actual_finish = _parse_date(entry.actual_finish, "actual_finish")
            for label, value in (("actual_start", actual_start), ("actual_finish", actual_finish)):
                # Work cannot actually have happened after the date progress
                # is being reported as of.
                if value is not None and value > data_date:
                    raise HTTPException(
                        status_code=422,
                        detail=f"{label} {value.isoformat()} for task {entry.task_id} is "
                        f"after the data date {data_date.isoformat()}. Move the data date "
                        "forward first.",
                    )
            if actual_start and actual_finish and actual_finish < actual_start:
                raise HTTPException(
                    status_code=422,
                    detail=f"Task {entry.task_id}: actual_finish is before actual_start.",
                )
            if all(
                value is None
                for value in (
                    entry.percent_complete,
                    entry.quantity_placed,
                    actual_start,
                    actual_finish,
                    entry.note,
                )
            ):
                raise HTTPException(
                    status_code=422,
                    detail=f"Task {entry.task_id}: the update reports nothing.",
                )
            session.add(
                ProgressUpdate(
                    project_id=project_id,
                    task_id=entry.task_id,
                    reported_on=reported_on,
                    percent_complete=entry.percent_complete,
                    quantity_placed=entry.quantity_placed,
                    actual_start=actual_start,
                    actual_finish=actual_finish,
                    note=entry.note,
                )
            )
        session.flush()
        return evaluate(session, project_id)


@router.get("/{project_id}/progress/history")
def progress_history(project_id: int, task_id: str | None = None) -> dict:
    with session_scope() as session:
        _require_project(session, project_id)
        query = select(ProgressUpdate).where(ProgressUpdate.project_id == project_id)
        if task_id:
            query = query.where(ProgressUpdate.task_id == task_id)
        rows = session.scalars(
            query.order_by(ProgressUpdate.reported_on.desc(), ProgressUpdate.id.desc())
        ).all()
        return {"updates": [row.as_dict() for row in rows]}


@router.delete("/{project_id}/progress/{task_id}")
def clear_task_progress(project_id: int, task_id: str) -> dict:
    """Wipe every report for one task, returning it to not started."""
    with session_scope() as session:
        _require_project(session, project_id)
        removed = (
            session.query(ProgressUpdate)
            .filter_by(project_id=project_id, task_id=task_id)
            .delete()
        )
        session.flush()
        payload = evaluate(session, project_id)
        payload["removed_updates"] = removed
        return payload
