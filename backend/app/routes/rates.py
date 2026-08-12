"""Rate library: read the effective library, persist per-project overrides."""

from __future__ import annotations

from copy import deepcopy

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm.attributes import flag_modified

from ..config import load_config
from ..db import Project, ScheduleRecord, session_scope
from ..schedule.calendar import WorkCalendar
from ..schedule.durations import RateLibrary, compute_duration
from ..schedule.lod import TaskGroup
from ..schedule.pipeline import _merge_rate_overrides, apply_cpm
from ..schemas import RatesUpdate

router = APIRouter(prefix="/api/projects", tags=["rates"])


@router.get("/{project_id}/rates")
def get_rates(project_id: int) -> dict:
    with session_scope() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found.")
        overrides = project.rate_overrides or {}
    base = load_config("rates")
    effective = _merge_rate_overrides(base, overrides) if overrides else base
    return {
        "effective": RateLibrary(effective).as_dict(),
        "overrides": overrides,
        "defaults": RateLibrary(base).as_dict(),
    }


@router.put("/{project_id}/rates")
def update_rates(project_id: int, payload: RatesUpdate) -> dict:
    """Store overrides and, by default, reprice the existing schedule in place."""
    overrides: dict = {}
    rules = [
        {k: v for k, v in rule.model_dump().items() if v is not None} for rule in payload.rules
    ]
    if rules:
        overrides["rules"] = rules
    if payload.default:
        overrides["default"] = payload.default
    if payload.count_fallback:
        overrides["count_fallback"] = payload.count_fallback

    with session_scope() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found.")
        project.rate_overrides = overrides

        repriced = 0
        if payload.recalculate:
            record = session.query(ScheduleRecord).filter_by(project_id=project_id).one_or_none()
            if record is not None:
                repriced = _reprice(record, overrides)

        return {"overrides": overrides, "repriced_tasks": repriced}


def _reprice(record: ScheduleRecord, overrides: dict) -> int:
    """Recompute durations for every task the user has not hand-edited."""
    library = RateLibrary(_merge_rate_overrides(load_config("rates"), overrides))
    # Detached copies: in-place mutation of the loaded JSON would not be
    # persisted (see _editable in routes/schedule.py).
    tasks = deepcopy(record.tasks or [])
    links = deepcopy(record.links or [])
    changed = 0

    for task in tasks:
        if task.get("rate_source") == "user_override":
            continue
        group = TaskGroup(
            key=(task.get("id"),),
            label=str(task.get("label") or ""),
            level=str(task.get("level") or "L3"),
            wbs_path=list(task.get("wbs_path") or []),
            work_package=str(task.get("work_package") or "Interior"),
            storey_id=task.get("storey_id"),
            storey_name=str(task.get("storey_name") or ""),
            storey_elevation=task.get("storey_elevation"),
            zone_name=task.get("zone_name"),
            ifc_class=task.get("ifc_class"),
            predefined_type=task.get("predefined_type"),
            type_name=task.get("type_name"),
            material=task.get("material"),
            element_ids=list(task.get("element_ids") or []),
            element_count=int(task.get("element_count") or 0),
            quantities=dict(task.get("quantities") or {}),
            quantity_source=str(task.get("quantity_source") or "none"),
        )
        result = compute_duration(group, library)
        if result.duration_days != task.get("duration_days"):
            changed += 1
        task.update(
            {
                "duration_days": result.duration_days,
                "quantity": result.quantity,
                "quantity_key": result.quantity_key,
                "unit": result.unit,
                "rate_id": result.rate_id,
                "rate_source": result.rate_source,
                "confidence": result.confidence,
                "crew": result.crew,
                "output_per_crew_day": result.output_per_crew_day,
            }
        )

    stored = record.calendar or {}
    calendar = WorkCalendar(
        start_date=stored.get("start_date"),
        work_days=stored.get("work_days"),
        holidays=stored.get("holidays"),
    )
    cpm_report = apply_cpm(tasks, links, calendar)
    report = dict(record.report or {})
    report["cpm"] = cpm_report
    record.tasks = tasks
    record.links = links
    record.report = report
    record.project_duration_days = float(cpm_report.get("project_duration_days") or 0)
    for column in ("tasks", "links", "report"):
        flag_modified(record, column)
    return changed
