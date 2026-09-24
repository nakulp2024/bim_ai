"""Project lifecycle: create, upload, parse, profile, LOD preview."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from sqlalchemy import select

from ..config import get_settings, load_config
from ..db import (
    BaselineRecord,
    ProgressUpdate,
    Project,
    load_elements,
    save_elements,
    session_scope,
)
from ..ifc.model import records_to_frame
from ..ifc.parser import parse_ifc
from ..ifc.profile import build_profile
from ..jobs import JobHandle, get_job_manager
from ..schedule.filtering import ElementFilter
from ..schedule.lod import LEVEL_INFO, predict_task_counts
from ..schedule.work_packages import WorkPackageClassifier
from ..schemas import LodPreviewRequest, ProjectCreate

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["projects"])

ALLOWED_SUFFIXES = {".ifc", ".ifcxml", ".ifczip"}


@router.post("")
def create_project(payload: ProjectCreate) -> dict:
    with session_scope() as session:
        project = Project(name=payload.name.strip() or "Untitled project", status="created")
        session.add(project)
        session.flush()
        return project.as_dict()


@router.get("")
def list_projects() -> dict:
    with session_scope() as session:
        projects = session.scalars(select(Project).order_by(Project.id.desc())).all()
        return {"projects": [project.as_dict() for project in projects]}


@router.get("/{project_id}")
def get_project(project_id: int) -> dict:
    with session_scope() as session:
        project = _require(session, project_id)
        return project.as_dict()


@router.delete("/{project_id}")
def delete_project(project_id: int) -> dict:
    settings = get_settings()
    with session_scope() as session:
        project = _require(session, project_id)
        if project.ifc_path:
            Path(project.ifc_path).unlink(missing_ok=True)
        # SQLite only honours ON DELETE CASCADE with foreign keys switched on,
        # so remove dependent rows explicitly rather than orphan them.
        session.query(ProgressUpdate).filter_by(project_id=project_id).delete()
        session.query(BaselineRecord).filter_by(project_id=project_id).delete()
        session.delete(project)
    shutil.rmtree(settings.project_dir / str(project_id), ignore_errors=True)
    return {"deleted": project_id}


@router.post("/{project_id}/upload")
async def upload_ifc(project_id: int, file: UploadFile = File(...)) -> dict:
    """Store the upload and kick off a background parse; returns a job id."""
    settings = get_settings()
    settings.ensure_dirs()

    suffix = Path(file.filename or "model.ifc").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Expected one of "
            f"{sorted(ALLOWED_SUFFIXES)}.",
        )

    destination = settings.upload_dir / f"{project_id}{suffix}"
    size = 0
    limit = settings.max_upload_mb * 1024 * 1024
    try:
        with destination.open("wb") as handle:
            while chunk := await file.read(4 * 1024 * 1024):
                size += len(chunk)
                if size > limit:
                    handle.close()
                    destination.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the {settings.max_upload_mb} MB limit.",
                    )
                handle.write(chunk)
    finally:
        await file.close()

    if size == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    with session_scope() as session:
        project = _require(session, project_id)
        project.ifc_filename = file.filename
        project.ifc_path = str(destination)
        project.status = "parsing"
        project.error = None

    job_id = get_job_manager().submit("parse", project_id, _make_parse_worker(project_id))
    return {"job_id": job_id, "project_id": project_id, "filename": file.filename, "bytes": size}


def _make_parse_worker(project_id: int):
    def worker(handle: JobHandle) -> dict:
        with session_scope() as session:
            project = session.get(Project, project_id)
            if project is None or not project.ifc_path:
                raise RuntimeError("project has no uploaded IFC file")
            path = project.ifc_path

        records, report = parse_ifc(path, progress=handle.progress)
        frame = records_to_frame(records)

        classifier = WorkPackageClassifier()
        if not frame.empty:
            frame["work_package"] = classifier.classify_frame(frame)
        profile = build_profile(frame, classifier)
        save_elements(project_id, frame)

        with session_scope() as session:
            project = session.get(Project, project_id)
            if project is not None:
                project.ifc_schema = report.schema
                project.element_count = report.elements_read
                project.parse_report = report.as_dict()
                project.profile = profile
                project.status = "parsed" if report.elements_read else "failed"
                if not report.elements_read:
                    project.error = (
                        "No schedulable elements were read from this file. "
                        + "; ".join(report.errors[:3])
                    )
        handle.progress(1.0, f"Parsed {report.elements_read} elements")
        return {
            "elements_read": report.elements_read,
            "schema": report.schema,
            "quantity_coverage_pct": report.quantity_coverage(),
            "errors": report.errors[:10],
        }

    return worker


@router.get("/{project_id}/profile")
def get_profile(project_id: int) -> dict:
    with session_scope() as session:
        project = _require(session, project_id)
        if project.status in ("created", "parsing"):
            raise HTTPException(status_code=409, detail=f"Project is {project.status}.")
        return {
            "project": project.as_dict(),
            "profile": project.profile or {},
            "parse_report": project.parse_report or {},
        }


@router.post("/{project_id}/lod-preview")
def lod_preview(project_id: int, payload: LodPreviewRequest) -> dict:
    """Predicted task count per level, so the picker can warn before committing."""
    with session_scope() as session:
        project = _require(session, project_id)
        if project.status in ("created", "parsing"):
            raise HTTPException(status_code=409, detail=f"Project is {project.status}.")

    frame = load_elements(project_id)
    if frame.empty:
        return {
            "levels": [
                {"level": level, **info, "task_count": 0, "is_default": level == "L3",
                 "warn": False}
                for level, info in LEVEL_INFO.items()
            ],
            "filter": {},
        }

    filters_config = load_config("filters")
    classifier = WorkPackageClassifier()
    if "work_package" not in frame.columns:
        frame["work_package"] = classifier.classify_frame(frame)

    kept, filter_report = ElementFilter(filters_config).apply(frame)
    levels = predict_task_counts(kept, payload.zone_split, classifier, filters_config)
    return {"levels": levels, "filter": filter_report.as_dict()}


def _require(session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found.")
    return project
