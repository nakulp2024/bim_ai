"""Model profile: what is actually in this IFC, before anyone picks a LOD."""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..schedule.work_packages import WorkPackageClassifier

# Property names that commonly carry a zone/phase split the user may want.
ZONE_LIKE_PROPERTIES = frozenset({"zone", "phase", "sector", "area", "wing", "block"})


def _counts(frame: pd.DataFrame, column: str, limit: int | None = None) -> list[dict[str, Any]]:
    if column not in frame or frame.empty:
        return []
    series = frame[column].fillna("(none)").astype(str).value_counts()
    if limit:
        series = series.head(limit)
    return [{"key": key, "count": int(value)} for key, value in series.items()]


def build_profile(frame: pd.DataFrame, classifier: WorkPackageClassifier) -> dict[str, Any]:
    """Summarise the element frame by class, storey, type and discipline."""
    if frame.empty:
        return {
            "element_count": 0,
            "by_class": [],
            "by_storey": [],
            "by_type": [],
            "by_discipline": [],
            "by_material": [],
            "storeys": [],
            "zones": [],
            "quantity_coverage": {"base_quantity": 0, "derived": 0, "none": 0, "coverage_pct": 0.0},
            "available_zone_properties": [],
        }

    working = frame.copy()
    if "work_package" not in working:
        working["work_package"] = classifier.classify_frame(working)

    storeys: list[dict[str, Any]] = []
    if "storey_id" in working:
        grouped = working.groupby(
            [
                working["storey_id"].fillna("(unassigned)"),
                working["storey_name"].fillna("(unassigned)"),
            ],
            dropna=False,
        )
        for (storey_id, storey_name), rows in grouped:
            elevations = rows["storey_elevation"].dropna()
            storeys.append(
                {
                    "storey_id": storey_id,
                    "name": storey_name,
                    "elevation": float(elevations.iloc[0]) if not elevations.empty else None,
                    "count": int(len(rows)),
                }
            )
        storeys.sort(key=lambda s: (s["elevation"] is None, s["elevation"] or 0.0))

    source_counts = working["quantity_source"].value_counts().to_dict()
    base = int(source_counts.get("base_quantity", 0))
    derived = int(source_counts.get("derived", 0))
    missing = int(source_counts.get("none", 0))
    total = max(len(working), 1)

    zone_properties: set[str] = set()
    if "property_sets" in working:
        for property_sets in working["property_sets"].head(2000):
            if not isinstance(property_sets, dict):
                continue
            for set_name, properties in property_sets.items():
                if not isinstance(properties, dict):
                    continue
                for property_name in properties:
                    if property_name.lower() in ZONE_LIKE_PROPERTIES:
                        zone_properties.add(f"{set_name}.{property_name}")

    return {
        "element_count": int(len(working)),
        "by_class": _counts(working, "ifc_class"),
        "by_storey": [{"key": s["name"], "count": s["count"]} for s in storeys],
        "by_type": _counts(working, "type_name", limit=50),
        "by_discipline": _counts(working, "work_package"),
        "by_material": _counts(working, "material", limit=50),
        "by_predefined_type": _counts(working, "predefined_type", limit=50),
        "storeys": storeys,
        "zones": _counts(working, "zone_name"),
        "quantity_coverage": {
            "base_quantity": base,
            "derived": derived,
            "none": missing,
            "coverage_pct": round(100.0 * (base + derived) / total, 2),
        },
        "available_zone_properties": sorted(zone_properties),
    }
