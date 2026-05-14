from fastapi import APIRouter, Depends, Query

from ..auth.jwt_tokens import current_user
from ..db import User
from ..speckle.client import SpeckleClient

router = APIRouter(prefix="/speckle", tags=["speckle"])


def _client(user: User) -> SpeckleClient:
    return SpeckleClient(user.speckle_access_token)


@router.get("/projects")
async def list_projects(
    user: User = Depends(current_user),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict]:
    return await _client(user).projects(limit=limit)


@router.get("/projects/{project_id}/models")
async def list_models(
    project_id: str,
    user: User = Depends(current_user),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict]:
    return await _client(user).models(project_id, limit=limit)


@router.get("/projects/{project_id}/models/{model_id}/versions")
async def list_versions(
    project_id: str,
    model_id: str,
    user: User = Depends(current_user),
    limit: int = Query(20, ge=1, le=100),
) -> list[dict]:
    return await _client(user).versions(project_id, model_id, limit=limit)
