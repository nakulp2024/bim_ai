"""The element record: the single row shape everything downstream consumes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from ..util import normalize_frame

# Quantity keys we normalise onto every element. Values are in SI (m, m2, m3).
QUANTITY_KEYS = (
    "NetVolume",
    "GrossVolume",
    "NetArea",
    "GrossArea",
    "NetSideArea",
    "Length",
    "Width",
    "Height",
    "Perimeter",
    "Count",
)

# Which quantity satisfies a rate expressed in a given unit, best first.
UNIT_QUANTITY_PREFERENCE: dict[str, tuple[str, ...]] = {
    "m3": ("NetVolume", "GrossVolume"),
    "m2": ("NetArea", "GrossArea", "NetSideArea"),
    "m": ("Length", "Perimeter", "Height", "Width"),
    "ea": ("Count",),
}


@dataclass
class ElementRecord:
    """One IFC product, flattened."""

    global_id: str
    ifc_class: str
    predefined_type: str | None = None
    name: str | None = None
    object_type: str | None = None
    type_name: str | None = None

    material: str | None = None
    material_kind: str | None = None  # single | layered | profile | constituent | None
    material_layers: list[str] = field(default_factory=list)

    site_name: str | None = None
    building_name: str | None = None
    storey_id: str | None = None
    storey_name: str | None = None
    storey_elevation: float | None = None
    container_class: str | None = None

    assembly_id: str | None = None       # GlobalId of the parent IfcElementAssembly
    assembly_name: str | None = None
    is_assembly: bool = False

    zone_id: str | None = None
    zone_name: str | None = None

    classification: str | None = None
    classification_system: str | None = None

    quantities: dict[str, float] = field(default_factory=dict)
    quantity_source: str = "none"  # base_quantity | derived | none
    property_sets: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Populated by the class hierarchy walk, used for is_a()-style matching
    # after the IFC file has been closed.
    class_hierarchy: list[str] = field(default_factory=list)

    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def records_to_frame(records: list[ElementRecord]) -> pd.DataFrame:
    """Build the element DataFrame, exploding quantities into their own columns."""
    if not records:
        columns = [f.name for f in ElementRecord.__dataclass_fields__.values()]
        frame = pd.DataFrame(columns=columns)
        for key in QUANTITY_KEYS:
            frame[f"qty_{key}"] = pd.Series(dtype="float64")
        return frame

    rows = []
    for record in records:
        row = record.as_dict()
        quantities = row.pop("quantities") or {}
        for key in QUANTITY_KEYS:
            value = quantities.get(key)
            row[f"qty_{key}"] = float(value) if value is not None else None
        row["quantities"] = quantities
        rows.append(row)

    frame = pd.DataFrame(rows)
    for key in QUANTITY_KEYS:
        column = f"qty_{key}"
        if column not in frame:
            frame[column] = None
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["storey_elevation"] = pd.to_numeric(frame.get("storey_elevation"), errors="coerce")
    return normalize_frame(frame)


def pick_quantity(row: Any, unit: str) -> tuple[float | None, str | None]:
    """Return the best available quantity for ``unit`` plus the key it came from."""
    for key in UNIT_QUANTITY_PREFERENCE.get(unit, ()):
        value = row.get(f"qty_{key}") if isinstance(row, dict) else getattr(row, f"qty_{key}", None)
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if numeric > 0 and numeric == numeric:  # NaN-safe
            return numeric, key
    return None, None
