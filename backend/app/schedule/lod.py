"""Schedule level of detail (SLOD): grouping elements into task groups.

Five levels, all selectable at runtime. Each level defines a grouping key over
the filtered element frame; an optional secondary zone split refines any level.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..config import load_config
from ..ifc.model import QUANTITY_KEYS
from .work_packages import WorkPackageClassifier

LEVELS = ("L1", "L2", "L3", "L4", "L5")

LEVEL_INFO: dict[str, dict[str, str]] = {
    "L1": {
        "name": "Project / Zone",
        "description": "One task per building storey (Site > Building > Storey only).",
    },
    "L2": {
        "name": "Discipline per storey",
        "description": "Storey x work package (Substructure, Superstructure, Envelope, "
        "MEP, Interior, Finishes).",
    },
    "L3": {
        "name": "Element class per storey",
        "description": "Storey x IfcClass/PredefinedType, e.g. 'L02 - Columns'. Default.",
    },
    "L4": {
        "name": "Type / material group",
        "description": "Storey x zone x IfcTypeObject or material, e.g. "
        "'L02 - 200mm Blockwork Walls'.",
    },
    "L5": {
        "name": "Individual element",
        "description": "One task per element. Task counts grow quickly on large models.",
    },
}

CLASS_LABELS = {
    "IfcBeam": "Beams",
    "IfcBuildingElementProxy": "Miscellaneous Elements",
    "IfcCableCarrierSegment": "Cable Containment",
    "IfcColumn": "Columns",
    "IfcCovering": "Coverings",
    "IfcCurtainWall": "Curtain Walling",
    "IfcDoor": "Doors",
    "IfcDuctSegment": "Ductwork",
    "IfcElementAssembly": "Assemblies",
    "IfcFooting": "Footings",
    "IfcFurniture": "Furniture",
    "IfcMember": "Members",
    "IfcPile": "Piles",
    "IfcPipeSegment": "Pipework",
    "IfcPlate": "Plates",
    "IfcRailing": "Railings",
    "IfcRamp": "Ramps",
    "IfcRoof": "Roofs",
    "IfcSanitaryTerminal": "Sanitaryware",
    "IfcSlab": "Slabs",
    "IfcStair": "Stairs",
    "IfcWall": "Walls",
    "IfcWindow": "Windows",
}

PREDEFINED_LABELS = {
    "PAD_FOOTING": "Pad Footings",
    "STRIP_FOOTING": "Strip Footings",
    "PILE_CAP": "Pile Caps",
    "FOOTING_BEAM": "Ground Beams",
    "FLOORING": "Floor Finishes",
    "CEILING": "Ceilings",
    "CLADDING": "Cladding",
    "ROOFING": "Roof Finishes",
    "BASESLAB": "Ground Slabs",
    "GROUNDSLAB": "Ground Slabs",
    "FLOOR": "Floor Slabs",
    "ROOF": "Roof Slabs",
    "LANDING": "Landings",
    "PARTITIONING": "Partitions",
    "SOLIDWALL": "Solid Walls",
    "PARAPET": "Parapets",
    "SHEAR": "Shear Walls",
}

UNASSIGNED_STOREY = "Unassigned"


def _pluralise_class(ifc_class: str) -> str:
    if ifc_class in CLASS_LABELS:
        return CLASS_LABELS[ifc_class]
    stripped = re.sub(r"^Ifc", "", ifc_class or "Element")
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", stripped)
    if spaced.endswith("s"):
        return spaced
    # Consonant + y -> ies ("Storey" stays "Storeys", "Assembly" -> "Assemblies").
    if len(spaced) > 1 and spaced.endswith("y") and spaced[-2].lower() not in "aeiou":
        return spaced[:-1] + "ies"
    return spaced + "s"


def humanize_class(ifc_class: str, predefined_type: str | None = None) -> str:
    """'IfcSlab' + 'FLOOR' -> 'Floor Slabs'; 'IfcCovering' + 'CEILING' -> 'Ceiling Coverings'.

    Two groups at the same level must never share a label, so an unmapped but
    meaningful PredefinedType is folded into the name rather than dropped.
    """
    plural = _pluralise_class(ifc_class)
    predefined = str(predefined_type or "").strip().upper()
    if not predefined or predefined in ("NOTDEFINED", "USERDEFINED"):
        return plural

    mapped = PREDEFINED_LABELS.get(predefined)
    if mapped:
        return mapped

    # Skip redundant qualifiers: IfcColumn + COLUMN should not read
    # "Column Columns".
    qualifier = predefined.replace("_", " ").title()
    bare = re.sub(r"^Ifc", "", ifc_class or "").lower()
    if qualifier.lower().replace(" ", "") in (bare, plural.lower().replace(" ", "")):
        return plural
    return f"{qualifier} {plural}"


@dataclass
class TaskGroup:
    """A candidate schedule task: a bucket of elements plus their totals."""

    key: tuple
    label: str
    level: str
    wbs_path: list[str]
    work_package: str
    storey_id: str | None
    storey_name: str
    storey_elevation: float | None
    zone_name: str | None
    ifc_class: str | None
    predefined_type: str | None
    type_name: str | None
    material: str | None
    element_ids: list[str] = field(default_factory=list)
    element_count: int = 0
    quantities: dict[str, float] = field(default_factory=dict)
    quantity_source: str = "none"
    aggregated_trivial: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "level": self.level,
            "wbs_path": self.wbs_path,
            "work_package": self.work_package,
            "storey_id": self.storey_id,
            "storey_name": self.storey_name,
            "storey_elevation": self.storey_elevation,
            "zone_name": self.zone_name,
            "ifc_class": self.ifc_class,
            "predefined_type": self.predefined_type,
            "type_name": self.type_name,
            "material": self.material,
            "element_ids": self.element_ids,
            "element_count": self.element_count,
            "quantities": self.quantities,
            "quantity_source": self.quantity_source,
            "aggregated_trivial": self.aggregated_trivial,
            "notes": self.notes,
        }


# --------------------------------------------------------------------------
# zone resolution
# --------------------------------------------------------------------------


def resolve_zone(row: dict[str, Any], zone_split: str | None) -> str | None:
    """``zone_split`` is either 'zone' (IfcZone/IfcSpatialZone) or 'Pset.Prop'."""
    if not zone_split:
        return None
    if zone_split == "zone":
        return row.get("zone_name") or None
    if "." in zone_split:
        set_name, property_name = zone_split.split(".", 1)
        property_sets = row.get("property_sets")
        if isinstance(property_sets, dict):
            bucket = property_sets.get(set_name)
            if isinstance(bucket, dict):
                value = bucket.get(property_name)
                if value not in (None, ""):
                    return str(value)
        return None
    property_sets = row.get("property_sets")
    if isinstance(property_sets, dict):
        for bucket in property_sets.values():
            if isinstance(bucket, dict) and zone_split in bucket:
                value = bucket[zone_split]
                if value not in (None, ""):
                    return str(value)
    return None


# --------------------------------------------------------------------------
# grouping
# --------------------------------------------------------------------------


def _material_label(row: dict[str, Any]) -> str | None:
    type_name = row.get("type_name")
    if type_name:
        return str(type_name)
    material = row.get("material")
    if material:
        return str(material)
    object_type = row.get("object_type")
    return str(object_type) if object_type else None


def _compose_label(descriptor: str | None, base: str) -> str:
    """'100mm Metal Stud Partition' + 'Partitions' -> '100mm Metal Stud Partitions'."""
    if not descriptor:
        return base
    singular = base[:-1] if base.endswith("s") else base
    if singular and singular.lower() in descriptor.lower():
        return descriptor if descriptor.rstrip().endswith("s") else f"{descriptor}s"
    return f"{descriptor} {base}"


def _element_label(row: dict[str, Any]) -> str:
    name = row.get("name") or row.get("type_name") or row.get("object_type")
    if name:
        return str(name)
    ifc_class = row.get("ifc_class") or "Element"
    return f"{re.sub(r'^Ifc', '', ifc_class)} {str(row.get('global_id'))[:8]}"


def _group_key(level: str, row: dict[str, Any], zone: str | None) -> tuple:
    storey = row.get("storey_id") or UNASSIGNED_STOREY
    if level == "L1":
        return (storey,)
    if level == "L2":
        return (storey, zone, row.get("work_package"))
    if level == "L3":
        return (storey, zone, row.get("ifc_class"), row.get("predefined_type"))
    if level == "L4":
        return (
            storey,
            zone,
            row.get("ifc_class"),
            row.get("predefined_type"),
            _material_label(row),
        )
    return (storey, zone, row.get("global_id"))


def _label_for(level: str, row: dict[str, Any], zone: str | None) -> str:
    storey_name = row.get("storey_name") or UNASSIGNED_STOREY
    zone_suffix = f" [{zone}]" if zone else ""
    ifc_class = row.get("ifc_class") or "Element"
    predefined = row.get("predefined_type")

    if level == "L1":
        return f"{storey_name} – All works"
    if level == "L2":
        return f"{storey_name}{zone_suffix} – {row.get('work_package')}"
    if level == "L3":
        return f"{storey_name}{zone_suffix} – {humanize_class(ifc_class, predefined)}"
    if level == "L4":
        descriptor = _material_label(row)
        base = humanize_class(ifc_class, predefined)
        return f"{storey_name}{zone_suffix} – {_compose_label(descriptor, base)}"
    return f"{storey_name}{zone_suffix} – {_element_label(row)}"


def _wbs_path(level: str, row: dict[str, Any], zone: str | None) -> list[str]:
    path = [
        str(row.get("site_name") or "Site"),
        str(row.get("building_name") or "Building"),
        str(row.get("storey_name") or UNASSIGNED_STOREY),
    ]
    if zone:
        path.append(str(zone))
    if level == "L1":
        return path
    path.append(str(row.get("work_package")))
    if level == "L2":
        return path
    path.append(humanize_class(row.get("ifc_class") or "", row.get("predefined_type")))
    if level in ("L3",):
        return path
    descriptor = _material_label(row)
    if descriptor:
        path.append(str(descriptor))
    return path


def _is_trivial_at_l5(row: dict[str, Any], min_volume: float | None, factor: float) -> bool:
    """A single element only deserves its own L5 task if it is measurable."""
    if row.get("quantity_source") == "none":
        return True
    if min_volume is None:
        return False
    volume = row.get("qty_NetVolume")
    try:
        volume = float(volume)
    except (TypeError, ValueError):
        return False
    if volume != volume:  # NaN
        return False
    return volume < float(min_volume) * factor


def group_elements(
    frame: pd.DataFrame,
    level: str = "L3",
    zone_split: str | None = None,
    classifier: WorkPackageClassifier | None = None,
    filters_config: dict[str, Any] | None = None,
) -> list[TaskGroup]:
    """Group a *filtered* element frame into task groups for ``level``."""
    level = (level or "L3").upper()
    if level not in LEVELS:
        raise ValueError(f"unknown level of detail: {level!r} (expected one of {LEVELS})")
    if frame.empty:
        return []

    classifier = classifier or WorkPackageClassifier()
    filters_config = filters_config if filters_config is not None else load_config("filters")
    aggregate_trivial = bool(filters_config.get("aggregate_trivial_at_l5", True))
    size_threshold = filters_config.get("size_threshold") or {}
    min_volume = size_threshold.get("min_net_volume_m3")
    trivial_factor = float(filters_config.get("l5_trivial_volume_factor", 3.0) or 3.0)

    rows = frame.to_dict(orient="records")
    if "work_package" not in frame.columns:
        packages = classifier.classify_frame(frame).tolist()
        for row, package in zip(rows, packages, strict=False):
            row["work_package"] = package

    buckets: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    bucket_level: dict[tuple, str] = {}

    for row in rows:
        zone = resolve_zone(row, zone_split)
        row_level = level
        if level == "L5" and aggregate_trivial and _is_trivial_at_l5(
            row, min_volume, trivial_factor
        ):
            # Never emit a task for a single trivial element: fold it into the
            # L4 bucket it belongs to.
            row_level = "L4"
        key = (row_level,) + _group_key(row_level, row, zone)
        buckets[key].append(row)
        bucket_level[key] = row_level

    groups: list[TaskGroup] = []
    for key, members in buckets.items():
        row_level = bucket_level[key]
        head = members[0]
        zone = resolve_zone(head, zone_split)

        quantities: dict[str, float] = {}
        for member in members:
            for quantity_key in QUANTITY_KEYS:
                value = member.get(f"qty_{quantity_key}")
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue
                if numeric != numeric:
                    continue
                quantities[quantity_key] = quantities.get(quantity_key, 0.0) + numeric
        quantities["Count"] = float(len(members))

        sources = {member.get("quantity_source") for member in members}
        if sources == {"base_quantity"}:
            source = "base_quantity"
        elif "base_quantity" in sources or "derived" in sources:
            source = "mixed" if len(sources) > 1 else sources.pop()
        else:
            source = "none"

        distinct_classes = {member.get("ifc_class") for member in members}
        distinct_materials = {
            member.get("material") for member in members if member.get("material")
        }

        group = TaskGroup(
            key=key,
            label=_label_for(row_level, head, zone),
            level=row_level,
            wbs_path=_wbs_path(row_level, head, zone),
            work_package=str(head.get("work_package") or "Interior"),
            storey_id=head.get("storey_id"),
            storey_name=str(head.get("storey_name") or UNASSIGNED_STOREY),
            storey_elevation=_float_or_none(head.get("storey_elevation")),
            zone_name=zone,
            ifc_class=head.get("ifc_class") if len(distinct_classes) == 1 else None,
            predefined_type=head.get("predefined_type"),
            type_name=head.get("type_name"),
            material=head.get("material") if len(distinct_materials) <= 1 else None,
            element_ids=[str(member.get("global_id")) for member in members],
            element_count=len(members),
            quantities=quantities,
            quantity_source=source,
            aggregated_trivial=(level == "L5" and row_level != "L5"),
        )
        if group.aggregated_trivial:
            group.notes.append(
                f"{len(members)} element(s) too small or unmeasured for individual L5 tasks; "
                "aggregated at L4."
            )
        groups.append(group)

    groups.sort(key=_sort_key)
    return groups


def _float_or_none(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return None if numeric != numeric else numeric


def _sort_key(group: TaskGroup) -> tuple:
    return (
        group.storey_elevation if group.storey_elevation is not None else float("inf"),
        group.storey_name,
        group.zone_name or "",
        group.work_package,
        group.ifc_class or "",
        group.label,
    )


def predict_task_counts(
    frame: pd.DataFrame,
    zone_split: str | None = None,
    classifier: WorkPackageClassifier | None = None,
    filters_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Task count per level, so the UI can warn before the user commits."""
    classifier = classifier or WorkPackageClassifier()
    results: list[dict[str, Any]] = []
    for level in LEVELS:
        groups = group_elements(frame, level, zone_split, classifier, filters_config)
        info = LEVEL_INFO[level]
        results.append(
            {
                "level": level,
                "name": info["name"],
                "description": info["description"],
                "task_count": len(groups),
                "is_default": level == "L3",
                "warn": len(groups) > 1000,
            }
        )
    return results
