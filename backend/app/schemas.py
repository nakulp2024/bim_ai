from pydantic import BaseModel, Field
from typing import Any


class ProjectCreated(BaseModel):
    project_id: str


class Element(BaseModel):
    ifc_guid: str
    express_id: int
    ifc_type: str
    name: str | None = None
    storey: str | None = None
    psets: dict[str, dict[str, Any]] = Field(default_factory=dict)


class IfcUploadResult(BaseModel):
    project_id: str
    element_count: int
    glb_url: str
    elements_url: str
