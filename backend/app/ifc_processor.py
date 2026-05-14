from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element

from .schemas import Element


class IfcConvertMissingError(RuntimeError):
    pass


def _find_ifcconvert() -> str:
    path = shutil.which("IfcConvert")
    if not path:
        raise IfcConvertMissingError(
            "IfcConvert binary not found on PATH. Install ifcopenshell's "
            "IfcConvert tool (https://blenderbim.org/docs-python/ifcconvert.html)."
        )
    return path


def extract_elements(ifc_path: Path) -> list[Element]:
    model = ifcopenshell.open(str(ifc_path))
    elements: list[Element] = []
    for el in model.by_type("IfcProduct"):
        if not getattr(el, "Representation", None):
            continue
        if not getattr(el, "GlobalId", None):
            continue
        try:
            psets = ifcopenshell.util.element.get_psets(el) or {}
        except Exception:
            psets = {}
        storey = None
        try:
            container = ifcopenshell.util.element.get_container(el)
            if container is not None:
                storey = getattr(container, "Name", None)
        except Exception:
            pass
        elements.append(
            Element(
                ifc_guid=el.GlobalId,
                express_id=el.id(),
                ifc_type=el.is_a(),
                name=getattr(el, "Name", None),
                storey=storey,
                psets=psets,
            )
        )
    return elements


def convert_to_glb(ifc_path: Path, out_path: Path) -> None:
    binary = _find_ifcconvert()
    cmd = [
        binary,
        str(ifc_path),
        str(out_path),
        "--use-element-guids",
        "--orient-shells",
        "-y",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"IfcConvert failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError("IfcConvert produced no output file.")


def write_elements_json(elements: list[Element], out_path: Path) -> None:
    out_path.write_text(
        json.dumps([e.model_dump() for e in elements], default=str),
        encoding="utf-8",
    )
