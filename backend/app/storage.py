from pathlib import Path
import os

DATA_ROOT = Path(os.environ.get("BIM_DATA_DIR", "/tmp/bim_ai_data")).resolve()


def project_dir(project_id: str) -> Path:
    p = DATA_ROOT / project_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def source_ifc_path(project_id: str) -> Path:
    return project_dir(project_id) / "source.ifc"


def glb_path(project_id: str) -> Path:
    return project_dir(project_id) / "model.glb"


def elements_path(project_id: str) -> Path:
    return project_dir(project_id) / "elements.json"
