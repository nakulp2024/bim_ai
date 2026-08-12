"""Export endpoints."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from ..db import Project, ScheduleRecord, session_scope
from ..exports import FORMATS

router = APIRouter(prefix="/api/projects", tags=["exports"])


@router.get("/{project_id}/export/{fmt}")
def export_schedule(project_id: int, fmt: str) -> Response:
    fmt = fmt.lower()
    if fmt not in FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown format '{fmt}'. Available: {sorted(FORMATS)}",
        )

    with session_scope() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found.")
        record = session.query(ScheduleRecord).filter_by(project_id=project_id).one_or_none()
        if record is None:
            raise HTTPException(
                status_code=404, detail=f"No schedule generated for project {project_id}."
            )
        schedule = record.as_dict()
        project_name = project.name

    media_type, extension, writer = FORMATS[fmt]
    try:
        payload = writer(schedule, project_name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Export failed: {exc}") from exc

    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", project_name).strip("_") or "schedule"
    filename = f"{safe_name}.{extension}"
    return Response(
        content=payload,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{project_id}/export")
def list_export_formats(project_id: int) -> dict:
    return {
        "formats": [
            {"id": "csv", "label": "CSV", "extension": "csv"},
            {"id": "xlsx", "label": "Excel (XLSX)", "extension": "xlsx"},
            {"id": "mspdi", "label": "MS Project XML", "extension": "xml"},
            {"id": "xer", "label": "Primavera P6 (XER)", "extension": "xer"},
            {"id": "json", "label": "Full JSON (4D linking)", "extension": "json"},
        ]
    }
