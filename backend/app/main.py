from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import storage
from .ifc_processor import (
    IfcConvertMissingError,
    convert_to_glb,
    extract_elements,
    write_elements_json,
)
from .schemas import IfcUploadResult, ProjectCreated

app = FastAPI(title="BIM AI Backend (M1)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/projects", response_model=ProjectCreated)
def create_project() -> ProjectCreated:
    project_id = uuid.uuid4().hex
    storage.project_dir(project_id)
    return ProjectCreated(project_id=project_id)


@app.post("/projects/{project_id}/ifc", response_model=IfcUploadResult)
async def upload_ifc(project_id: str, file: UploadFile = File(...)) -> IfcUploadResult:
    if not file.filename or not file.filename.lower().endswith(".ifc"):
        raise HTTPException(status_code=400, detail="File must be a .ifc upload.")

    ifc_path = storage.source_ifc_path(project_id)
    with ifc_path.open("wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)

    try:
        elements = extract_elements(ifc_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse IFC: {e}") from e

    write_elements_json(elements, storage.elements_path(project_id))

    try:
        convert_to_glb(ifc_path, storage.glb_path(project_id))
    except IfcConvertMissingError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"glTF conversion failed: {e}") from e

    return IfcUploadResult(
        project_id=project_id,
        element_count=len(elements),
        glb_url=f"/projects/{project_id}/model.glb",
        elements_url=f"/projects/{project_id}/elements",
    )


@app.get("/projects/{project_id}/model.glb")
def get_glb(project_id: str) -> FileResponse:
    path = storage.glb_path(project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Model not found.")
    return FileResponse(path, media_type="model/gltf-binary", filename="model.glb")


@app.get("/projects/{project_id}/elements")
def get_elements(project_id: str) -> JSONResponse:
    path = storage.elements_path(project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Elements not found.")
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))
