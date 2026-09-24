"""Geometry for the 4D viewer: build on demand, then serve from cache."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import get_settings
from ..db import Project, session_scope
from ..ifc.geometry import extract_geometry, read_manifest, write_cache
from ..jobs import JobHandle, get_job_manager

router = APIRouter(prefix="/api/projects", tags=["geometry"])


def _cache_dir(project_id: int):
    return get_settings().project_dir / str(project_id) / "geometry"


@router.post("/{project_id}/geometry")
def build_geometry(project_id: int, force: bool = False) -> dict:
    """Tessellate the model in the background. Idempotent unless ``force``."""
    with session_scope() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found.")
        if not project.ifc_path:
            raise HTTPException(status_code=409, detail="Upload an IFC model first.")
        if project.geometry_status == "building":
            raise HTTPException(status_code=409, detail="Geometry is already being built.")
        if project.geometry_status == "ready" and not force and read_manifest(
            _cache_dir(project_id)
        ):
            return {"job_id": None, "status": "ready"}
        project.geometry_status = "building"
        ifc_path = project.ifc_path

    def worker(handle: JobHandle) -> dict:
        try:
            result = extract_geometry(ifc_path, progress=handle.progress)
            write_cache(result, _cache_dir(project_id))
        except Exception:
            with session_scope() as session:
                project = session.get(Project, project_id)
                if project is not None:
                    project.geometry_status = "failed"
            raise
        with session_scope() as session:
            project = session.get(Project, project_id)
            if project is not None:
                project.geometry_status = "ready"
        return {
            "element_count": result.manifest["element_count"],
            "triangle_count": result.manifest["triangle_count"],
            "warnings": result.warnings,
        }

    job_id = get_job_manager().submit("geometry", project_id, worker)
    return {"job_id": job_id, "status": "building"}


@router.get("/{project_id}/geometry")
def get_geometry_manifest(project_id: int) -> dict:
    with session_scope() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found.")
        status = project.geometry_status
    if status == "building":
        raise HTTPException(status_code=409, detail="Geometry is still being built.")
    manifest = read_manifest(_cache_dir(project_id))
    if manifest is None:
        raise HTTPException(
            status_code=404,
            detail="No geometry built for this project yet. POST to this URL to build it.",
        )
    return manifest


@router.get("/{project_id}/geometry/buffer")
def get_geometry_buffer(project_id: int) -> FileResponse:
    path = _cache_dir(project_id) / "geometry.bin"
    if not path.exists():
        raise HTTPException(status_code=404, detail="No geometry built for this project yet.")
    return FileResponse(
        path,
        media_type="application/octet-stream",
        # Content never changes for a given build; let the browser keep it.
        headers={"Cache-Control": "private, max-age=3600"},
    )
