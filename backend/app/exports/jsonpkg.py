"""Full JSON package: tasks + logic + source GlobalIds, for 4D linking."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "ifc-schedule/1.0"


PROGRESS_FIELDS = (
    "status",
    "percent_complete",
    "quantity_placed",
    "actual_start",
    "actual_finish",
    "remaining_duration",
    "forecast_start",
    "forecast_finish",
    "forecast_critical",
    "baseline_start",
    "baseline_finish",
    "planned_percent",
    "start_variance_days",
    "finish_variance_days",
    "schedule_flag",
    "delay_cause",
    "progress_assumptions",
)


def _progress_block(progress: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    state = progress.get(task_id)
    if not state:
        return None
    return {field: state.get(field) for field in PROGRESS_FIELDS}


def to_json_package(schedule: dict[str, Any], project_name: str = "Schedule") -> bytes:
    tasks = schedule.get("tasks") or []
    tracking = schedule.get("progress") or {}
    progress = tracking.get("tasks") or {}
    package = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "project": {
            "name": project_name,
            "options": schedule.get("options") or {},
            "calendar": schedule.get("calendar") or {},
        },
        "tasks": [
            {
                "id": task.get("id"),
                "wbs_code": task.get("wbs_code"),
                "wbs_path": task.get("wbs_path"),
                "name": task.get("label"),
                "level": task.get("level"),
                "work_package": task.get("work_package"),
                "storey": {
                    "id": task.get("storey_id"),
                    "name": task.get("storey_name"),
                    "elevation": task.get("storey_elevation"),
                },
                "zone": task.get("zone_name"),
                "classification": {
                    "ifc_class": task.get("ifc_class"),
                    "predefined_type": task.get("predefined_type"),
                    "type_name": task.get("type_name"),
                    "material": task.get("material"),
                },
                "quantity": {
                    "value": task.get("quantity"),
                    "unit": task.get("unit"),
                    "key": task.get("quantity_key"),
                    "source": task.get("quantity_source"),
                },
                "duration_days": task.get("duration_days"),
                "crew": task.get("crew"),
                "rate_id": task.get("rate_id"),
                "rate_source": task.get("rate_source"),
                "confidence": task.get("confidence"),
                "dates": {
                    "early_start": task.get("start_date"),
                    "early_finish": task.get("finish_date"),
                    "late_start": task.get("late_start_date"),
                    "late_finish": task.get("late_finish_date"),
                },
                "float": {
                    "total": task.get("total_float"),
                    "free": task.get("free_float"),
                    "critical": task.get("is_critical"),
                },
                "predecessors": task.get("predecessors") or [],
                "element_count": task.get("element_count"),
                # The whole point of the export: 4D linking needs these.
                "source_global_ids": task.get("element_ids") or [],
                "user_edited": task.get("user_edited", False),
                # Present only when the schedule is tracked; 4D consumers use
                # this to replay what actually happened, not just the plan.
                "progress": _progress_block(progress, task.get("id")),
            }
            for task in tasks
        ],
        "progress": {
            "summary": tracking.get("summary"),
            "baseline": tracking.get("baseline"),
        }
        if tracking
        else None,
        "links": schedule.get("links") or [],
        "report": schedule.get("report") or {},
    }
    return json.dumps(package, indent=2, default=str).encode("utf-8")
