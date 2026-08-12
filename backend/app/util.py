"""Small coercion helpers.

Element frames mix real values with pandas NaN, JSON nulls and IFC's own
"NOTDEFINED" placeholders. Everything downstream reads through these two
helpers so a missing value is always ``None``/``""`` and never a float NaN.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# Columns that must stay textual; NaN in any of them breaks string matching.
TEXT_COLUMNS = (
    "global_id",
    "ifc_class",
    "predefined_type",
    "name",
    "object_type",
    "type_name",
    "material",
    "material_kind",
    "site_name",
    "building_name",
    "storey_id",
    "storey_name",
    "container_class",
    "assembly_id",
    "assembly_name",
    "zone_id",
    "zone_name",
    "classification",
    "classification_system",
    "quantity_source",
    "work_package",
)


def as_text(value: Any, default: str = "") -> str:
    """Coerce anything to a stripped string, mapping NaN/None to ``default``."""
    if value is None:
        return default
    if isinstance(value, float) and value != value:  # NaN
        return default
    text = str(value).strip()
    return text or default


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Replace NaN with None in text columns so `.get(...) or ''` behaves."""
    if frame.empty:
        return frame
    for column in TEXT_COLUMNS:
        if column in frame.columns:
            frame[column] = frame[column].astype(object).where(frame[column].notna(), None)
    return frame
