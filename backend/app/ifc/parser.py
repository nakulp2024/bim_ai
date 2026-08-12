"""IFC -> element records.

Supports IFC2X3 and IFC4/IFC4X3. Every extraction step is individually guarded:
a malformed relationship, a missing inverse attribute or a broken geometry
representation degrades that one element (recorded in ``warnings``) instead of
failing the run.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import ifcopenshell

from ..config import get_settings
from .model import QUANTITY_KEYS, ElementRecord

log = logging.getLogger(__name__)

ProgressFn = Callable[[float, str], None]

# Spatial containers are context, not work. IfcSpace is kept because the filter
# stage reports it (and a user may switch it back on).
SPATIAL_CLASSES = ("IfcSite", "IfcBuilding", "IfcBuildingStorey", "IfcSpatialZone")

QUANTITY_ALIASES = {
    "netvolume": "NetVolume",
    "grossvolume": "GrossVolume",
    "netarea": "NetArea",
    "grossarea": "GrossArea",
    "netsidearea": "NetSideArea",
    "grosssidearea": "GrossArea",
    "netfootprintarea": "NetArea",
    "grossfootprintarea": "GrossArea",
    "length": "Length",
    "width": "Width",
    "height": "Height",
    "perimeter": "Perimeter",
    "count": "Count",
}


@dataclass
class ParseReport:
    """Everything that happened during a parse, for the per-run report."""

    schema: str = ""
    file_size_bytes: int = 0
    total_entities: int = 0
    products_seen: int = 0
    elements_read: int = 0
    skipped_spatial: int = 0
    quantities_from_base: int = 0
    quantities_derived: int = 0
    quantities_missing: int = 0
    geometry_failures: int = 0
    geometry_skipped_over_cap: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def quantity_coverage(self) -> float:
        if not self.elements_read:
            return 0.0
        covered = self.quantities_from_base + self.quantities_derived
        return round(100.0 * covered / self.elements_read, 2)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "file_size_bytes": self.file_size_bytes,
            "total_entities": self.total_entities,
            "products_seen": self.products_seen,
            "elements_read": self.elements_read,
            "skipped_spatial": self.skipped_spatial,
            "quantities_from_base": self.quantities_from_base,
            "quantities_derived": self.quantities_derived,
            "quantities_missing": self.quantities_missing,
            "quantity_coverage_pct": self.quantity_coverage(),
            "geometry_failures": self.geometry_failures,
            "geometry_skipped_over_cap": self.geometry_skipped_over_cap,
            "errors": self.errors[:200],
            "warnings": self.warnings[:200],
        }


# --------------------------------------------------------------------------
# schema helpers
# --------------------------------------------------------------------------

_hierarchy_cache: dict[tuple[str, str], list[str]] = {}


def class_hierarchy(schema: str, class_name: str) -> list[str]:
    """Return ``[class_name, ...supertypes]`` so is_a() survives file closure."""
    key = (schema, class_name)
    cached = _hierarchy_cache.get(key)
    if cached is not None:
        return cached
    chain: list[str] = []
    try:
        wrapper = ifcopenshell.ifcopenshell_wrapper
        declaration = wrapper.schema_by_name(schema).declaration_by_name(class_name)
        while declaration is not None:
            chain.append(declaration.name())
            declaration = declaration.supertype()
    except Exception:  # unknown schema or class: fall back to the leaf name
        chain = [class_name]
    _hierarchy_cache[key] = chain
    return chain


def length_unit_scale(ifc_file: ifcopenshell.file) -> float:
    """Metres per file length unit."""
    try:
        import ifcopenshell.util.unit as unit_util

        scale = unit_util.calculate_unit_scale(ifc_file)
        if scale and scale > 0:
            return float(scale)
    except Exception:
        pass
    return 1.0


def _safe(entity: Any, attribute: str, default: Any = None) -> Any:
    try:
        value = getattr(entity, attribute, default)
    except Exception:
        return default
    return default if value is None else value


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# --------------------------------------------------------------------------
# relationship indexes
# --------------------------------------------------------------------------


class _Index:
    """Precomputed relationship lookups keyed by entity id (much faster than
    walking inverse attributes per element on large files)."""

    def __init__(self, ifc_file: ifcopenshell.file, report: ParseReport) -> None:
        self.file = ifc_file
        self.report = report
        self.container: dict[int, Any] = {}
        self.referenced: dict[int, Any] = {}
        self.aggregate_parent: dict[int, Any] = {}
        self.definitions: dict[int, list[Any]] = {}
        self.type_of: dict[int, Any] = {}
        self.material_of: dict[int, Any] = {}
        self.classification_of: dict[int, list[Any]] = {}
        self.group_of: dict[int, list[Any]] = {}
        self._build()

    def _each(self, class_name: str):
        try:
            return self.file.by_type(class_name)
        except Exception:
            return []

    def _build(self) -> None:
        for rel in self._each("IfcRelContainedInSpatialStructure"):
            structure = _safe(rel, "RelatingStructure")
            for element in _safe(rel, "RelatedElements", []) or []:
                if element is not None and structure is not None:
                    self.container[element.id()] = structure

        for rel in self._each("IfcRelReferencedInSpatialStructure"):
            structure = _safe(rel, "RelatingStructure")
            for element in _safe(rel, "RelatedElements", []) or []:
                if element is not None and structure is not None:
                    self.referenced.setdefault(element.id(), structure)

        for rel in self._each("IfcRelAggregates"):
            parent = _safe(rel, "RelatingObject")
            for child in _safe(rel, "RelatedObjects", []) or []:
                if child is not None and parent is not None:
                    self.aggregate_parent[child.id()] = parent

        for rel in self._each("IfcRelNests"):
            parent = _safe(rel, "RelatingObject")
            for child in _safe(rel, "RelatedObjects", []) or []:
                if child is not None and parent is not None:
                    self.aggregate_parent.setdefault(child.id(), parent)

        for rel in self._each("IfcRelDefinesByProperties"):
            definition = _safe(rel, "RelatingPropertyDefinition")
            if definition is None:
                continue
            for obj in _safe(rel, "RelatedObjects", []) or []:
                if obj is not None:
                    self.definitions.setdefault(obj.id(), []).append(definition)

        for rel in self._each("IfcRelDefinesByType"):
            type_object = _safe(rel, "RelatingType")
            for obj in _safe(rel, "RelatedObjects", []) or []:
                if obj is not None and type_object is not None:
                    self.type_of[obj.id()] = type_object

        for rel in self._each("IfcRelAssociatesMaterial"):
            material = _safe(rel, "RelatingMaterial")
            for obj in _safe(rel, "RelatedObjects", []) or []:
                if obj is not None and material is not None:
                    self.material_of.setdefault(obj.id(), material)

        for rel in self._each("IfcRelAssociatesClassification"):
            reference = _safe(rel, "RelatingClassification")
            for obj in _safe(rel, "RelatedObjects", []) or []:
                if obj is not None and reference is not None:
                    self.classification_of.setdefault(obj.id(), []).append(reference)

        for rel in self._each("IfcRelAssignsToGroup"):
            group = _safe(rel, "RelatingGroup")
            if group is None:
                continue
            for obj in _safe(rel, "RelatedObjects", []) or []:
                if obj is not None:
                    self.group_of.setdefault(obj.id(), []).append(group)


# --------------------------------------------------------------------------
# per-element extraction
# --------------------------------------------------------------------------


def _spatial_chain(index: _Index, element: Any) -> list[Any]:
    """Walk up from an element through containment then aggregation."""
    chain: list[Any] = []
    current = index.container.get(element.id()) or index.referenced.get(element.id())
    if current is None:
        # Elements nested in an assembly inherit the assembly's container.
        parent = index.aggregate_parent.get(element.id())
        hops = 0
        while parent is not None and hops < 10:
            current = index.container.get(parent.id()) or index.referenced.get(parent.id())
            if current is not None:
                break
            parent = index.aggregate_parent.get(parent.id())
            hops += 1
    hops = 0
    while current is not None and hops < 12:
        chain.append(current)
        current = index.aggregate_parent.get(current.id())
        hops += 1
    return chain


def _extract_material(material: Any, depth: int = 0) -> tuple[str | None, str | None, list[str]]:
    """Return (label, kind, layers) for any flavour of material association."""
    if material is None or depth > 4:
        return None, None, []
    try:
        kind = material.is_a()
    except Exception:
        return None, None, []

    if kind == "IfcMaterial":
        return _clean(_safe(material, "Name")), "single", []

    if kind == "IfcMaterialLayerSetUsage":
        return _extract_material(_safe(material, "ForLayerSet"), depth + 1)

    if kind == "IfcMaterialLayerSet":
        layers = []
        for layer in _safe(material, "MaterialLayers", []) or []:
            inner = _safe(layer, "Material")
            name = _clean(_safe(inner, "Name")) or "Unnamed"
            thickness = _safe(layer, "LayerThickness")
            layers.append(f"{name} {thickness}" if thickness else name)
        label = _clean(_safe(material, "LayerSetName")) or " / ".join(
            _clean(_safe(_safe(layer, "Material"), "Name")) or "Unnamed"
            for layer in (_safe(material, "MaterialLayers", []) or [])
        )
        return label or None, "layered", layers

    if kind == "IfcMaterialProfileSetUsage":
        return _extract_material(_safe(material, "ForProfileSet"), depth + 1)

    if kind == "IfcMaterialProfileSet":
        profiles = [
            _clean(_safe(_safe(profile, "Material"), "Name")) or "Unnamed"
            for profile in (_safe(material, "MaterialProfiles", []) or [])
        ]
        label = _clean(_safe(material, "Name")) or " / ".join(profiles)
        return label or None, "profile", profiles

    if kind == "IfcMaterialConstituentSet":
        parts = [
            _clean(_safe(_safe(part, "Material"), "Name")) or "Unnamed"
            for part in (_safe(material, "MaterialConstituents", []) or [])
        ]
        label = _clean(_safe(material, "Name")) or " / ".join(parts)
        return label or None, "constituent", parts

    if kind == "IfcMaterialList":
        names = [
            _clean(_safe(item, "Name")) or "Unnamed"
            for item in (_safe(material, "Materials", []) or [])
        ]
        return (" / ".join(names) or None), "constituent", names

    return _clean(_safe(material, "Name")), "single", []


def _quantity_value(quantity: Any) -> tuple[str | None, float | None, str | None]:
    """Return (normalised name, value, dimension) for one IfcPhysicalQuantity."""
    try:
        kind = quantity.is_a()
    except Exception:
        return None, None, None
    mapping = {
        "IfcQuantityVolume": ("VolumeValue", "volume"),
        "IfcQuantityArea": ("AreaValue", "area"),
        "IfcQuantityLength": ("LengthValue", "length"),
        "IfcQuantityCount": ("CountValue", "count"),
    }
    if kind not in mapping:
        return None, None, None
    attribute, dimension = mapping[kind]
    raw = _safe(quantity, attribute)
    if raw is None:
        return None, None, None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None, None, None
    raw_name = _clean(_safe(quantity, "Name")) or ""
    normalised = QUANTITY_ALIASES.get(raw_name.replace(" ", "").lower())
    if normalised is None and raw_name in QUANTITY_KEYS:
        normalised = raw_name
    return normalised, value, dimension


def _extract_definitions(
    index: _Index, element: Any, scale: float
) -> tuple[dict[str, float], dict[str, dict[str, Any]]]:
    """Pull Qto_* quantities and Pset_* properties, converting units to SI."""
    quantities: dict[str, float] = {}
    property_sets: dict[str, dict[str, Any]] = {}
    factors = {"length": scale, "area": scale**2, "volume": scale**3, "count": 1.0}

    for definition in index.definitions.get(element.id(), []):
        try:
            kind = definition.is_a()
        except Exception:
            continue
        if kind == "IfcElementQuantity":
            for quantity in _safe(definition, "Quantities", []) or []:
                name, value, dimension = _quantity_value(quantity)
                if name is None or value is None:
                    continue
                converted = value * factors.get(dimension or "count", 1.0)
                # Highest wins when a model declares the same quantity twice.
                if converted > quantities.get(name, float("-inf")):
                    quantities[name] = converted
        elif kind == "IfcPropertySet":
            set_name = _clean(_safe(definition, "Name")) or "Pset"
            bucket = property_sets.setdefault(set_name, {})
            for prop in _safe(definition, "HasProperties", []) or []:
                prop_name = _clean(_safe(prop, "Name"))
                if not prop_name:
                    continue
                raw = _safe(prop, "NominalValue")
                value = _safe(raw, "wrappedValue", raw)
                if isinstance(value, (str, int, float, bool)) or value is None:
                    bucket[prop_name] = value
    return quantities, property_sets


def _derive_geometry(element: Any, settings_geom: Any, scale: float) -> dict[str, float] | None:
    """Bounding box + mesh volume from the element's geometry, in SI."""
    import ifcopenshell.geom as ifc_geom

    shape = ifc_geom.create_shape(settings_geom, element)
    verts = list(shape.geometry.verts)
    faces = list(shape.geometry.faces)
    if len(verts) < 9:
        return None

    xs = verts[0::3]
    ys = verts[1::3]
    zs = verts[2::3]
    dx = (max(xs) - min(xs)) * scale
    dy = (max(ys) - min(ys)) * scale
    dz = (max(zs) - min(zs)) * scale

    volume = 0.0
    for i in range(0, len(faces) - 2, 3):
        a, b, c = faces[i] * 3, faces[i + 1] * 3, faces[i + 2] * 3
        ax, ay, az = verts[a], verts[a + 1], verts[a + 2]
        bx, by, bz = verts[b], verts[b + 1], verts[b + 2]
        cx, cy, cz = verts[c], verts[c + 1], verts[c + 2]
        volume += (
            ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)
        ) / 6.0
    volume = abs(volume) * (scale**3)

    dims = sorted([dx, dy, dz], reverse=True)
    diagonal = (dx**2 + dy**2 + dz**2) ** 0.5
    return {
        "NetVolume": volume,
        # Largest bounding-box face: a decent stand-in for the surface a trade
        # actually works on (wall elevation, slab plan area).
        "NetArea": dims[0] * dims[1],
        "Length": dims[0],
        "Width": dims[1],
        "Height": dz,
        "BBoxDiagonal": diagonal,
    }


# --------------------------------------------------------------------------
# public entry point
# --------------------------------------------------------------------------


def parse_ifc(
    path: str | Path,
    progress: ProgressFn | None = None,
    derive_geometry: bool = True,
    max_derived: int | None = None,
) -> tuple[list[ElementRecord], ParseReport]:
    """Read an IFC file into element records plus a report of what happened."""
    path = Path(path)
    report = ParseReport(file_size_bytes=path.stat().st_size if path.exists() else 0)
    cap = max_derived if max_derived is not None else get_settings().max_derived_geometry

    def emit(fraction: float, message: str) -> None:
        if progress:
            try:
                progress(fraction, message)
            except Exception:
                pass

    emit(0.02, "Opening IFC file")
    try:
        ifc_file = ifcopenshell.open(str(path))
    except Exception as exc:
        report.errors.append(f"Could not open IFC file: {exc}")
        return [], report

    report.schema = str(_safe(ifc_file, "schema", "unknown"))
    try:
        report.total_entities = len(ifc_file.wrapped_data.entity_names())
    except Exception:
        try:
            report.total_entities = sum(1 for _ in ifc_file)
        except Exception:
            report.total_entities = 0

    scale = length_unit_scale(ifc_file)
    emit(0.06, f"Indexing relationships ({report.schema})")
    index = _Index(ifc_file, report)

    try:
        products = ifc_file.by_type("IfcProduct")
    except Exception as exc:
        report.errors.append(f"No IfcProduct entities readable: {exc}")
        return [], report
    report.products_seen = len(products)

    settings_geom = None
    if derive_geometry:
        try:
            # Aliased: a bare `import ifcopenshell.geom` here would rebind
            # `ifcopenshell` as a function-local and break the calls above.
            import ifcopenshell.geom as ifc_geom

            settings_geom = ifc_geom.settings()
            try:
                settings_geom.set("use-world-coords", True)
            except Exception:
                # ifcopenshell < 0.8 keyword-style settings
                settings_geom.set(settings_geom.USE_WORLD_COORDS, True)
        except Exception as exc:
            report.warnings.append(f"Geometry engine unavailable, skipping derivation: {exc}")
            settings_geom = None

    records: list[ElementRecord] = []
    derived_count = 0
    total = max(len(products), 1)

    for position, product in enumerate(products):
        if position % 2000 == 0:
            emit(0.10 + 0.80 * position / total, f"Reading elements {position}/{total}")
        try:
            ifc_class = product.is_a()
        except Exception:
            report.errors.append("Entity with unreadable class skipped")
            continue

        if ifc_class in SPATIAL_CLASSES:
            report.skipped_spatial += 1
            continue

        global_id = _clean(_safe(product, "GlobalId"))
        if not global_id:
            global_id = f"__noguid_{product.id()}"
            report.warnings.append(f"{ifc_class} #{product.id()} has no GlobalId")

        record = ElementRecord(
            global_id=global_id,
            ifc_class=ifc_class,
            name=_clean(_safe(product, "Name")),
            object_type=_clean(_safe(product, "ObjectType")),
        )
        record.class_hierarchy = class_hierarchy(report.schema, ifc_class)
        record.is_assembly = "IfcElementAssembly" in record.class_hierarchy

        predefined = _clean(_safe(product, "PredefinedType"))
        if predefined == "USERDEFINED" and record.object_type:
            predefined = record.object_type
        record.predefined_type = predefined

        # --- type object -----------------------------------------------
        type_object = index.type_of.get(product.id())
        if type_object is not None:
            record.type_name = _clean(_safe(type_object, "Name")) or _clean(
                _safe(type_object, "ElementType")
            )
            if record.predefined_type in (None, "NOTDEFINED", "USERDEFINED"):
                type_predefined = _clean(_safe(type_object, "PredefinedType"))
                if type_predefined and type_predefined not in ("NOTDEFINED", "USERDEFINED"):
                    record.predefined_type = type_predefined

        # --- spatial placement -------------------------------------------
        try:
            for container in _spatial_chain(index, product):
                container_class = container.is_a()
                if record.container_class is None:
                    record.container_class = container_class
                if container_class == "IfcBuildingStorey" and record.storey_id is None:
                    record.storey_id = _clean(_safe(container, "GlobalId"))
                    record.storey_name = _clean(_safe(container, "Name")) or "Unnamed storey"
                    elevation = _safe(container, "Elevation")
                    try:
                        record.storey_elevation = (
                            float(elevation) * scale if elevation is not None else None
                        )
                    except (TypeError, ValueError):
                        record.storey_elevation = None
                elif container_class == "IfcBuilding" and record.building_name is None:
                    record.building_name = _clean(_safe(container, "Name")) or "Building"
                elif container_class == "IfcSite" and record.site_name is None:
                    record.site_name = _clean(_safe(container, "Name")) or "Site"
                elif container_class == "IfcSpatialZone" and record.zone_id is None:
                    record.zone_id = _clean(_safe(container, "GlobalId"))
                    record.zone_name = _clean(_safe(container, "Name")) or "Zone"
        except Exception as exc:
            record.warnings.append(f"spatial: {exc}")

        # --- assembly parent ---------------------------------------------
        parent = index.aggregate_parent.get(product.id())
        try:
            if parent is not None and parent.is_a("IfcElementAssembly"):
                record.assembly_id = _clean(_safe(parent, "GlobalId"))
                record.assembly_name = _clean(_safe(parent, "Name")) or "Assembly"
        except Exception:
            pass

        # --- zone membership ---------------------------------------------
        try:
            for group in index.group_of.get(product.id(), []):
                if group.is_a("IfcZone") or group.is_a("IfcSpatialZone"):
                    record.zone_id = _clean(_safe(group, "GlobalId"))
                    record.zone_name = _clean(_safe(group, "Name")) or "Zone"
                    break
        except Exception:
            pass

        # --- material -----------------------------------------------------
        try:
            material = index.material_of.get(product.id())
            if material is None and type_object is not None:
                material = index.material_of.get(type_object.id())
            label, kind, layers = _extract_material(material)
            record.material, record.material_kind, record.material_layers = label, kind, layers
        except Exception as exc:
            record.warnings.append(f"material: {exc}")

        # --- classification -----------------------------------------------
        try:
            references = index.classification_of.get(product.id()) or (
                index.classification_of.get(type_object.id(), []) if type_object else []
            )
            for reference in references:
                identification = _clean(_safe(reference, "Identification")) or _clean(
                    _safe(reference, "ItemReference")
                )
                label = _clean(_safe(reference, "Name"))
                if identification or label:
                    record.classification = " ".join(x for x in (identification, label) if x)
                    system = _safe(reference, "ReferencedSource")
                    record.classification_system = _clean(_safe(system, "Name")) or _clean(
                        _safe(system, "Source")
                    )
                    break
        except Exception as exc:
            record.warnings.append(f"classification: {exc}")

        # --- quantities ------------------------------------------------------
        try:
            quantities, property_sets = _extract_definitions(index, product, scale)
            if not quantities and type_object is not None:
                quantities, _ = _extract_definitions(index, type_object, scale)
            record.quantities = quantities
            record.property_sets = property_sets
        except Exception as exc:
            record.warnings.append(f"quantities: {exc}")
            record.quantities = {}

        if record.quantities:
            record.quantity_source = "base_quantity"
            report.quantities_from_base += 1
        elif settings_geom is not None and not record.is_assembly:
            if _safe(product, "Representation") is None:
                # Nothing to derive from; not a geometry engine failure.
                record.warnings.append("no quantities and no geometric representation")
                report.quantities_missing += 1
            elif derived_count >= cap:
                report.geometry_skipped_over_cap += 1
                report.quantities_missing += 1
            else:
                try:
                    derived = _derive_geometry(product, settings_geom, scale)
                except Exception:
                    derived = None
                    report.geometry_failures += 1
                if derived:
                    record.quantities = {
                        k: v for k, v in derived.items() if k != "BBoxDiagonal" and v > 0
                    }
                    record.quantities["BBoxDiagonal"] = derived["BBoxDiagonal"]
                    record.quantity_source = "derived"
                    report.quantities_derived += 1
                    derived_count += 1
                else:
                    report.quantities_missing += 1
        else:
            report.quantities_missing += 1

        records.append(record)
        report.elements_read += 1

    emit(0.92, "Rolling up assembly quantities")
    _rollup_assemblies(records)
    emit(0.96, f"Read {report.elements_read} elements")
    return records, report


def _rollup_assemblies(records: list[ElementRecord]) -> None:
    """Give every IfcElementAssembly the summed quantities of its children."""
    assemblies = {r.global_id: r for r in records if r.is_assembly}
    if not assemblies:
        return
    for record in records:
        parent = assemblies.get(record.assembly_id or "")
        if parent is None or record is parent:
            continue
        for key, value in record.quantities.items():
            if key == "BBoxDiagonal":
                continue
            parent.quantities[key] = parent.quantities.get(key, 0.0) + value
        if parent.quantity_source == "none":
            parent.quantity_source = record.quantity_source
    for parent in assemblies.values():
        if parent.quantities:
            parent.quantities.setdefault("Count", 1.0)
