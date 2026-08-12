"""Schedule generation and editing."""

from __future__ import annotations

import logging
from copy import deepcopy

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm.attributes import flag_modified

from ..config import load_config
from ..db import Project, ScheduleRecord, load_elements, session_scope
from ..jobs import JobHandle, get_job_manager
from ..schedule.calendar import WorkCalendar
from ..schedule.pipeline import ScheduleOptions, apply_cpm, generate_schedule
from ..schemas import CalendarUpdate, LinkCreate, ScheduleRequest, TaskUpdate

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["schedule"])


@router.post("/{project_id}/schedule")
def create_schedule(project_id: int, payload: ScheduleRequest) -> dict:
    with session_scope() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found.")
        if project.status not in ("parsed", "ready", "scheduling", "failed"):
            raise HTTPException(
                status_code=409,
                detail=f"Project is {project.status}; upload and parse an IFC first.",
            )
        project.status = "scheduling"
        project.schedule_options = payload.model_dump()

    job_id = get_job_manager().submit(
        "schedule", project_id, _make_schedule_worker(project_id, payload)
    )
    return {"job_id": job_id, "project_id": project_id}


def _make_schedule_worker(project_id: int, payload: ScheduleRequest):
    def worker(handle: JobHandle) -> dict:
        frame = load_elements(project_id)
        if frame.empty:
            raise RuntimeError("No parsed elements for this project.")

        with session_scope() as session:
            project = session.get(Project, project_id)
            rate_overrides = (project.rate_overrides or {}) if project else {}
            parse_report = (project.parse_report or {}) if project else {}

        options = ScheduleOptions.from_dict(payload.model_dump())
        options.rate_overrides = rate_overrides or None

        result = generate_schedule(
            frame, options, parse_report=parse_report, progress=handle.progress
        )

        with session_scope() as session:
            project = session.get(Project, project_id)
            record = session.query(ScheduleRecord).filter_by(project_id=project_id).one_or_none()
            if record is None:
                record = ScheduleRecord(project_id=project_id)
                session.add(record)
            record.level = options.level
            record.zone_split = options.zone_split
            record.tasks = result.tasks
            record.links = result.links
            record.calendar = result.calendar
            record.report = result.report
            record.options = result.options
            record.project_duration_days = float(
                result.report.get("cpm", {}).get("project_duration_days") or 0
            )
            if project is not None:
                project.status = "ready"
                project.error = None

        handle.progress(1.0, f"{len(result.tasks)} tasks")
        return {
            "task_count": len(result.tasks),
            "link_count": len(result.links),
            "project_duration_days": result.report.get("cpm", {}).get("project_duration_days"),
        }

    return worker


@router.get("/{project_id}/schedule")
def get_schedule(project_id: int) -> dict:
    with session_scope() as session:
        record = _require_schedule(session, project_id)
        return record.as_dict()


@router.get("/{project_id}/run-report")
def get_run_report(project_id: int) -> dict:
    with session_scope() as session:
        record = _require_schedule(session, project_id)
        return record.report or {}


# --------------------------------------------------------------------------
# editing
# --------------------------------------------------------------------------


@router.patch("/{project_id}/tasks/{task_id}")
def update_task(project_id: int, task_id: str, payload: TaskUpdate) -> dict:
    with session_scope() as session:
        record = _require_schedule(session, project_id)
        tasks, links = _editable(record)
        task = next((t for t in tasks if t.get("id") == task_id), None)
        if task is None:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found.")

        if payload.label is not None:
            task["label"] = payload.label
        if payload.duration_days is not None:
            task["duration_days"] = payload.duration_days
            task["confidence"] = "high"
            task["rate_source"] = "user_override"
        if payload.crew is not None:
            task["crew"] = payload.crew
        if payload.work_package is not None:
            task["work_package"] = payload.work_package
        if payload.predecessors is not None:
            links = [link for link in links if link.get("successor_id") != task_id]
            for incoming in payload.predecessors:
                if incoming.id == task_id or not any(t.get("id") == incoming.id for t in tasks):
                    continue
                links.append(
                    {
                        "predecessor_id": incoming.id,
                        "successor_id": task_id,
                        "type": incoming.type,
                        "lag": incoming.lag,
                        "origin": "user",
                    }
                )
        task["user_edited"] = True

        _recalculate(record, tasks, links)
        return record.as_dict()


@router.delete("/{project_id}/tasks/{task_id}")
def delete_task(project_id: int, task_id: str) -> dict:
    with session_scope() as session:
        record = _require_schedule(session, project_id)
        all_tasks, all_links = _editable(record)
        tasks = [t for t in all_tasks if t.get("id") != task_id]
        if len(tasks) == len(all_tasks):
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found.")
        links = [
            link
            for link in all_links
            if link.get("predecessor_id") != task_id and link.get("successor_id") != task_id
        ]
        _recalculate(record, tasks, links)
        return record.as_dict()


@router.post("/{project_id}/links")
def create_link(project_id: int, payload: LinkCreate) -> dict:
    with session_scope() as session:
        record = _require_schedule(session, project_id)
        tasks, existing_links = _editable(record)
        ids = {task.get("id") for task in tasks}
        if payload.predecessor_id not in ids or payload.successor_id not in ids:
            raise HTTPException(status_code=404, detail="Unknown task id in link.")
        if payload.predecessor_id == payload.successor_id:
            raise HTTPException(status_code=400, detail="A task cannot precede itself.")

        links = [
            link
            for link in existing_links
            if not (
                link.get("predecessor_id") == payload.predecessor_id
                and link.get("successor_id") == payload.successor_id
            )
        ]
        links.append({**payload.model_dump(), "origin": "user"})
        _recalculate(record, tasks, links)
        return record.as_dict()


@router.delete("/{project_id}/links")
def delete_link(project_id: int, predecessor_id: str, successor_id: str) -> dict:
    with session_scope() as session:
        record = _require_schedule(session, project_id)
        tasks, existing_links = _editable(record)
        links = [
            link
            for link in existing_links
            if not (
                link.get("predecessor_id") == predecessor_id
                and link.get("successor_id") == successor_id
            )
        ]
        _recalculate(record, tasks, links)
        return record.as_dict()


@router.put("/{project_id}/calendar")
def update_calendar(project_id: int, payload: CalendarUpdate) -> dict:
    with session_scope() as session:
        record = _require_schedule(session, project_id)
        calendar = dict(record.calendar or {})
        if payload.start_date is not None:
            calendar["start_date"] = payload.start_date
        if payload.work_days is not None:
            calendar["work_days"] = payload.work_days
        if payload.holidays is not None:
            calendar["holidays"] = payload.holidays
        record.calendar = calendar
        tasks, links = _editable(record)
        _recalculate(record, tasks, links)
        return record.as_dict()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _editable(record: ScheduleRecord) -> tuple[list[dict], list[dict]]:
    """Detached copies of the stored tasks and links.

    Mutating the loaded JSON in place leaves SQLAlchemy unable to see a change,
    so the UPDATE is never emitted and the edit is silently lost on reload.
    """
    return deepcopy(record.tasks or []), deepcopy(record.links or [])


def _recalculate(record: ScheduleRecord, tasks: list[dict], links: list[dict]) -> None:
    """Re-run CPM after an edit and write everything back onto the record."""
    stored = record.calendar or load_config("sequencing").get("calendar") or {}
    calendar = WorkCalendar(
        start_date=stored.get("start_date"),
        work_days=stored.get("work_days"),
        holidays=stored.get("holidays"),
    )
    cpm_report = apply_cpm(tasks, links, calendar)
    report = dict(record.report or {})
    report["cpm"] = cpm_report
    report.setdefault("grouping", {})["task_count"] = len(tasks)
    report["sequencing"] = {**(report.get("sequencing") or {}), "link_count": len(links)}
    report["edited"] = True

    record.tasks = tasks
    record.links = links
    record.calendar = calendar.as_dict()
    record.report = report
    record.project_duration_days = float(cpm_report.get("project_duration_days") or 0)
    for column in ("tasks", "links", "calendar", "report"):
        flag_modified(record, column)


def _require_schedule(session, project_id: int) -> ScheduleRecord:
    record = session.query(ScheduleRecord).filter_by(project_id=project_id).one_or_none()
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"No schedule generated for project {project_id}."
        )
    return record
