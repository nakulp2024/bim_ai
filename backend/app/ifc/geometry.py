"""Mesh extraction for the 4D viewer.

Tessellates every renderable product once and packs the result into two
merged buffers - positions and triangle indices - plus a JSON manifest that
records which slice of those buffers belongs to which GlobalId. The browser
draws the whole model in one call and recolours an element by writing into
its slice of a colour buffer, which is what makes 4D playback cheap.

Two conversions happen here so the client never has to think about them:

* **Axes.** IFC is Z-up; three.js is Y-up. (x, y, z) becomes (x, z, -y).
* **Origin.** Real models are often georeferenced far from (0, 0, 0), where
  float32 cannot hold millimetres and vertices visibly jitter. Everything is
  re-centred on the footprint's midpoint, ground level at y = 0, and the
  offset is recorded in the manifest.
"""

from __future__ import annotations

import json
import logging
import multiprocessing
import uuid
from array import array
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import ifcopenshell

log = logging.getLogger(__name__)

ProgressFn = Callable[[float, str], None]

MANIFEST_VERSION = 1

# Voids, abstract zones and drafting entities have geometry but are not work.
EXCLUDED_CLASSES = (
    "IfcSpace",
    "IfcOpeningElement",
    "IfcAnnotation",
    "IfcGrid",
    "IfcVirtualElement",
    "IfcSite",  # terrain dwarfs the building and is rarely scheduled
)

# A few million triangles is about the ceiling for a smooth browser viewer.
DEFAULT_MAX_TRIANGLES = 3_000_000


@dataclass
class GeometryResult:
    manifest: dict[str, Any]
    buffer: bytes
    warnings: list[str] = field(default_factory=list)


def _assembly_parent(ifc_file: ifcopenshell.file, product: Any) -> str | None:
    """GlobalId of the IfcElementAssembly a part belongs to, if any.

    Assembly children are collapsed into their parent before scheduling, so
    they appear in no task themselves; the viewer resolves them through this.
    """
    try:
        for rel in getattr(product, "Decomposes", None) or []:
            parent = getattr(rel, "RelatingObject", None)
            if parent is not None and parent.is_a("IfcElementAssembly"):
                return parent.GlobalId
    except Exception:
        return None
    return None


def extract_geometry(
    path: str | Path,
    progress: ProgressFn | None = None,
    max_triangles: int = DEFAULT_MAX_TRIANGLES,
    threads: int | None = None,
    excluded_classes: tuple[str, ...] = EXCLUDED_CLASSES,
) -> GeometryResult:
    """Tessellate an IFC file into merged buffers plus a per-element manifest."""
    import ifcopenshell.geom as ifc_geom

    def emit(fraction: float, message: str) -> None:
        if progress:
            try:
                progress(fraction, message)
            except Exception:
                pass

    warnings: list[str] = []
    emit(0.02, "Opening IFC file")
    ifc_file = ifcopenshell.open(str(path))

    settings = ifc_geom.settings()
    settings.set("use-world-coords", True)

    positions = array("f")
    indices = array("I")
    elements: list[dict[str, Any]] = []
    skipped_over_budget = 0
    failures = 0

    iterator = ifc_geom.iterator(
        settings,
        ifc_file,
        threads or max(1, multiprocessing.cpu_count()),
        exclude=list(excluded_classes),
    )

    emit(0.05, "Tessellating")
    try:
        started = iterator.initialize()
    except Exception as exc:
        warnings.append(f"geometry engine could not start: {exc}")
        started = False

    triangle_count = 0
    if started:
        while True:
            try:
                shape = iterator.get()
                verts = shape.geometry.verts
                faces = shape.geometry.faces
            except Exception:
                failures += 1
                verts, faces = (), ()
                shape = None

            if shape is not None and len(verts) >= 9 and len(faces) >= 3:
                triangles = len(faces) // 3
                if triangle_count + triangles > max_triangles:
                    skipped_over_budget += 1
                else:
                    vertex_start = len(positions) // 3
                    index_start = len(indices)
                    # IFC Z-up -> three.js Y-up.
                    for i in range(0, len(verts), 3):
                        positions.append(verts[i])
                        positions.append(verts[i + 2])
                        positions.append(-verts[i + 1])
                    indices.extend(vertex_start + int(face) for face in faces)
                    triangle_count += triangles

                    product = None
                    try:
                        product = ifc_file.by_guid(shape.guid)
                    except Exception:
                        product = None
                    elements.append(
                        {
                            "global_id": shape.guid,
                            "ifc_class": product.is_a() if product is not None else None,
                            "name": getattr(product, "Name", None) if product is not None else None,
                            "parent_id": _assembly_parent(ifc_file, product)
                            if product is not None
                            else None,
                            "vertex_start": vertex_start,
                            "vertex_count": len(verts) // 3,
                            "index_start": index_start,
                            "index_count": len(faces),
                        }
                    )

            try:
                done = iterator.progress()
                if len(elements) % 200 == 0:
                    emit(0.05 + 0.85 * done / 100.0, f"Tessellated {len(elements)} elements")
            except Exception:
                pass
            if not iterator.next():
                break

    if skipped_over_budget:
        warnings.append(
            f"{skipped_over_budget} element(s) skipped: the model exceeds the "
            f"{max_triangles:,}-triangle viewer budget"
        )
    if failures:
        warnings.append(f"{failures} element(s) failed to tessellate")

    emit(0.92, "Centring model")
    origin, bounds = _recentre(positions, elements)

    buffer = positions.tobytes() + indices.tobytes()
    manifest = {
        "version": MANIFEST_VERSION,
        "up_axis": "y",
        "units": "m",
        "origin_offset": origin,
        "bounds": bounds,
        "element_count": len(elements),
        "vertex_count": len(positions) // 3,
        "triangle_count": triangle_count,
        "buffers": {
            "positions": {"offset": 0, "length": len(positions), "type": "float32"},
            "indices": {
                "offset": len(positions) * 4,
                "length": len(indices),
                "type": "uint32",
            },
        },
        "excluded_classes": list(excluded_classes),
        "elements": elements,
        "warnings": warnings,
    }
    emit(0.98, f"{len(elements)} elements, {triangle_count:,} triangles")
    return GeometryResult(manifest=manifest, buffer=buffer, warnings=warnings)


def _recentre(
    positions: array, elements: list[dict[str, Any]]
) -> tuple[list[float], dict[str, list[float]]]:
    """Shift the model so its footprint is centred on the origin, ground at 0.

    Also records each element's own bounding box, which the viewer uses for
    picking and for framing a selection.
    """
    if not positions:
        return [0.0, 0.0, 0.0], {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0]}

    xs = positions[0::3]
    ys = positions[1::3]
    zs = positions[2::3]
    # Y is up after the axis swap: sit the lowest point on the ground plane.
    offset = [
        (min(xs) + max(xs)) / 2.0,
        min(ys),
        (min(zs) + max(zs)) / 2.0,
    ]
    for i in range(0, len(positions), 3):
        positions[i] -= offset[0]
        positions[i + 1] -= offset[1]
        positions[i + 2] -= offset[2]

    for element in elements:
        start = element["vertex_start"] * 3
        end = start + element["vertex_count"] * 3
        chunk = positions[start:end]
        element["bbox"] = {
            "min": [min(chunk[0::3]), min(chunk[1::3]), min(chunk[2::3])],
            "max": [max(chunk[0::3]), max(chunk[1::3]), max(chunk[2::3])],
        }

    return offset, {
        "min": [min(positions[0::3]), min(positions[1::3]), min(positions[2::3])],
        "max": [max(positions[0::3]), max(positions[1::3]), max(positions[2::3])],
    }


# --------------------------------------------------------------------------
# caching
# --------------------------------------------------------------------------


def write_cache(result: GeometryResult, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "geometry.json"
    buffer_path = directory / "geometry.bin"
    # Clients version the buffer URL with this, so a rebuild can never be
    # paired with a browser-cached buffer from the previous build.
    result.manifest["build_id"] = uuid.uuid4().hex
    # Buffer first: a manifest on disk is the signal that the pair is ready.
    buffer_path.write_bytes(result.buffer)
    manifest_path.write_text(json.dumps(result.manifest), encoding="utf-8")
    return manifest_path, buffer_path


def read_manifest(directory: Path) -> dict[str, Any] | None:
    path = directory / "geometry.json"
    if not path.exists() or not (directory / "geometry.bin").exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
