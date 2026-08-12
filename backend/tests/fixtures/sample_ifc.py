"""Builds a small but realistic IFC model for the test suite.

Deliberately includes the awkward cases the pipeline has to survive:
  * three storeys with elevations, plus one element with no spatial container
  * base quantities on most elements, none on a few (geometry fallback)
  * fasteners, an opening, an annotation and a space (all noise)
  * an IfcElementAssembly with children (collapse case)
  * two wall materials and a typed wall (L4 grouping case)
  * a tiny proxy below the size threshold, and unmeasured stairs that survive
    filtering but cannot stand alone as L5 tasks
  * an IfcZone grouping spaces, and a Pset carrying a Sector property
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import ifcopenshell


def _guid() -> str:
    return ifcopenshell.guid.compress(uuid.uuid4().hex)


class SampleModelBuilder:
    def __init__(self, schema: str = "IFC4") -> None:
        self.schema = schema
        self.file = ifcopenshell.file(schema=schema)
        self.owner_history = None
        self._setup_project()

    # -- scaffolding -------------------------------------------------------

    def _setup_project(self) -> None:
        f = self.file
        person = f.create_entity("IfcPerson", FamilyName="Test")
        organisation = f.create_entity("IfcOrganization", Name="IFC Schedule Tests")
        person_org = f.create_entity(
            "IfcPersonAndOrganization", ThePerson=person, TheOrganization=organisation
        )
        application = f.create_entity(
            "IfcApplication",
            ApplicationDeveloper=organisation,
            Version="1.0",
            ApplicationFullName="sample-builder",
            ApplicationIdentifier="sample-builder",
        )
        self.owner_history = f.create_entity(
            "IfcOwnerHistory",
            OwningUser=person_org,
            OwningApplication=application,
            ChangeAction="ADDED",
            CreationDate=int(time.time()),
        )

        length_unit = f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")
        area_unit = f.create_entity("IfcSIUnit", UnitType="AREAUNIT", Name="SQUARE_METRE")
        volume_unit = f.create_entity("IfcSIUnit", UnitType="VOLUMEUNIT", Name="CUBIC_METRE")
        units = f.create_entity(
            "IfcUnitAssignment", Units=[length_unit, area_unit, volume_unit]
        )

        axis = f.create_entity(
            "IfcAxis2Placement3D",
            Location=f.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0)),
        )
        self.context = f.create_entity(
            "IfcGeometricRepresentationContext",
            ContextType="Model",
            CoordinateSpaceDimension=3,
            Precision=1e-5,
            WorldCoordinateSystem=axis,
        )
        self.body_context = f.create_entity(
            "IfcGeometricRepresentationSubContext",
            ContextIdentifier="Body",
            ContextType="Model",
            ParentContext=self.context,
            TargetView="MODEL_VIEW",
        )

        self.project = f.create_entity(
            "IfcProject",
            GlobalId=_guid(),
            OwnerHistory=self.owner_history,
            Name="Sample Tower",
            RepresentationContexts=[self.context],
            UnitsInContext=units,
        )

        self.site = self._spatial("IfcSite", "Main Site")
        self.building = self._spatial("IfcBuilding", "Block A")
        self._aggregate(self.project, [self.site])
        self._aggregate(self.site, [self.building])

        self.storeys: dict[str, object] = {}
        for name, elevation in (("L00", 0.0), ("L01", 3.5), ("L02", 7.0)):
            storey = f.create_entity(
                "IfcBuildingStorey",
                GlobalId=_guid(),
                OwnerHistory=self.owner_history,
                Name=name,
                CompositionType="ELEMENT",
                Elevation=elevation,
                ObjectPlacement=self._placement(0.0, 0.0, elevation),
            )
            self.storeys[name] = storey
        self._aggregate(self.building, list(self.storeys.values()))

    def _spatial(self, ifc_class: str, name: str):
        return self.file.create_entity(
            ifc_class,
            GlobalId=_guid(),
            OwnerHistory=self.owner_history,
            Name=name,
            CompositionType="ELEMENT",
            ObjectPlacement=self._placement(0.0, 0.0, 0.0),
        )

    def _placement(self, x: float, y: float, z: float):
        return self.file.create_entity(
            "IfcLocalPlacement",
            RelativePlacement=self.file.create_entity(
                "IfcAxis2Placement3D",
                Location=self.file.create_entity(
                    "IfcCartesianPoint", Coordinates=(float(x), float(y), float(z))
                ),
            ),
        )

    def _aggregate(self, parent, children) -> None:
        self.file.create_entity(
            "IfcRelAggregates",
            GlobalId=_guid(),
            OwnerHistory=self.owner_history,
            RelatingObject=parent,
            RelatedObjects=list(children),
        )

    # -- content -----------------------------------------------------------

    def add_element(
        self,
        ifc_class: str,
        name: str,
        storey: str | None = "L00",
        predefined_type: str | None = None,
        quantities: dict[str, float] | None = None,
        material: str | list[str] | None = None,
        type_name: str | None = None,
        object_type: str | None = None,
        geometry: tuple[float, float, float] | None = None,
        properties: dict[str, dict[str, object]] | None = None,
        classification: tuple[str, str, str] | None = None,
    ):
        f = self.file
        kwargs: dict[str, object] = {
            "GlobalId": _guid(),
            "OwnerHistory": self.owner_history,
            "Name": name,
            "ObjectPlacement": self._placement(0.0, 0.0, 0.0),
        }
        if object_type:
            kwargs["ObjectType"] = object_type
        element = f.create_entity(ifc_class, **kwargs)
        if predefined_type is not None and hasattr(element, "PredefinedType"):
            try:
                element.PredefinedType = predefined_type
            except Exception:
                pass

        if storey is not None:
            self.contain(element, storey)
        if quantities:
            self.add_quantities(element, quantities)
        if material:
            self.add_material(element, material)
        if type_name:
            self.add_type(element, ifc_class, type_name, predefined_type)
        if geometry:
            self.add_box_geometry(element, *geometry)
        if properties:
            self.add_properties(element, properties)
        if classification:
            self.add_classification(element, *classification)
        return element

    def contain(self, element, storey: str) -> None:
        self.file.create_entity(
            "IfcRelContainedInSpatialStructure",
            GlobalId=_guid(),
            OwnerHistory=self.owner_history,
            RelatingStructure=self.storeys[storey],
            RelatedElements=[element],
        )

    def add_quantities(self, element, quantities: dict[str, float]) -> None:
        f = self.file
        entries = []
        for key, value in quantities.items():
            if key in ("NetVolume", "GrossVolume"):
                entries.append(
                    f.create_entity("IfcQuantityVolume", Name=key, VolumeValue=float(value))
                )
            elif "Area" in key:
                entries.append(f.create_entity("IfcQuantityArea", Name=key, AreaValue=float(value)))
            elif key == "Count":
                entries.append(
                    f.create_entity("IfcQuantityCount", Name=key, CountValue=float(value))
                )
            else:
                entries.append(
                    f.create_entity("IfcQuantityLength", Name=key, LengthValue=float(value))
                )
        quantity_set = f.create_entity(
            "IfcElementQuantity",
            GlobalId=_guid(),
            OwnerHistory=self.owner_history,
            Name=f"Qto_{element.is_a()[3:]}BaseQuantities",
            Quantities=entries,
        )
        f.create_entity(
            "IfcRelDefinesByProperties",
            GlobalId=_guid(),
            OwnerHistory=self.owner_history,
            RelatedObjects=[element],
            RelatingPropertyDefinition=quantity_set,
        )

    def add_properties(self, element, property_sets: dict[str, dict[str, object]]) -> None:
        f = self.file
        for set_name, properties in property_sets.items():
            entries = []
            for key, value in properties.items():
                entries.append(
                    f.create_entity(
                        "IfcPropertySingleValue",
                        Name=key,
                        NominalValue=f.create_entity("IfcLabel", str(value)),
                    )
                )
            property_set = f.create_entity(
                "IfcPropertySet",
                GlobalId=_guid(),
                OwnerHistory=self.owner_history,
                Name=set_name,
                HasProperties=entries,
            )
            f.create_entity(
                "IfcRelDefinesByProperties",
                GlobalId=_guid(),
                OwnerHistory=self.owner_history,
                RelatedObjects=[element],
                RelatingPropertyDefinition=property_set,
            )

    def add_material(self, element, material: str | list[str]) -> None:
        f = self.file
        if isinstance(material, str):
            relating = f.create_entity("IfcMaterial", Name=material)
        else:
            layers = [
                f.create_entity(
                    "IfcMaterialLayer",
                    Material=f.create_entity("IfcMaterial", Name=name),
                    LayerThickness=0.1,
                )
                for name in material
            ]
            relating = f.create_entity(
                "IfcMaterialLayerSet", MaterialLayers=layers, LayerSetName=" + ".join(material)
            )
        f.create_entity(
            "IfcRelAssociatesMaterial",
            GlobalId=_guid(),
            OwnerHistory=self.owner_history,
            RelatedObjects=[element],
            RelatingMaterial=relating,
        )

    def add_type(
        self, element, ifc_class: str, type_name: str, predefined_type: str | None
    ) -> None:
        f = self.file
        type_class = f"{ifc_class}Type"
        try:
            type_object = f.create_entity(
                type_class,
                GlobalId=_guid(),
                OwnerHistory=self.owner_history,
                Name=type_name,
            )
        except Exception:
            return
        if predefined_type and hasattr(type_object, "PredefinedType"):
            try:
                type_object.PredefinedType = predefined_type
            except Exception:
                pass
        f.create_entity(
            "IfcRelDefinesByType",
            GlobalId=_guid(),
            OwnerHistory=self.owner_history,
            RelatedObjects=[element],
            RelatingType=type_object,
        )

    def add_classification(self, element, system: str, code: str, label: str) -> None:
        f = self.file
        source = f.create_entity("IfcClassification", Name=system, Source=system)
        reference = f.create_entity(
            "IfcClassificationReference",
            Identification=code,
            Name=label,
            ReferencedSource=source,
        )
        f.create_entity(
            "IfcRelAssociatesClassification",
            GlobalId=_guid(),
            OwnerHistory=self.owner_history,
            RelatedObjects=[element],
            RelatingClassification=reference,
        )

    def add_box_geometry(self, element, x: float, y: float, z: float) -> None:
        """A simple extruded rectangle, so ifcopenshell.geom has something real."""
        f = self.file
        profile = f.create_entity(
            "IfcRectangleProfileDef",
            ProfileType="AREA",
            XDim=float(x),
            YDim=float(y),
            Position=f.create_entity(
                "IfcAxis2Placement2D",
                Location=f.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0)),
            ),
        )
        solid = f.create_entity(
            "IfcExtrudedAreaSolid",
            SweptArea=profile,
            Position=f.create_entity(
                "IfcAxis2Placement3D",
                Location=f.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0)),
            ),
            ExtrudedDirection=f.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0)),
            Depth=float(z),
        )
        shape = f.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=self.body_context,
            RepresentationIdentifier="Body",
            RepresentationType="SweptSolid",
            Items=[solid],
        )
        element.Representation = f.create_entity(
            "IfcProductDefinitionShape", Representations=[shape]
        )

    def add_assembly(self, name: str, storey: str, children_specs: list[dict]):
        assembly = self.add_element(
            "IfcElementAssembly", name, storey=storey, predefined_type="RIGID_FRAME"
        )
        children = []
        for spec in children_specs:
            child = self.add_element(storey=None, **spec)
            children.append(child)
        self._aggregate(assembly, children)
        return assembly, children

    def add_zone(self, name: str, spaces: list) -> object:
        zone = self.file.create_entity(
            "IfcZone", GlobalId=_guid(), OwnerHistory=self.owner_history, Name=name
        )
        self.file.create_entity(
            "IfcRelAssignsToGroup",
            GlobalId=_guid(),
            OwnerHistory=self.owner_history,
            RelatedObjects=list(spaces),
            RelatingGroup=zone,
        )
        return zone

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file.write(str(path))
        return path


def build_sample_model(schema: str = "IFC4") -> SampleModelBuilder:
    """The canonical fixture used across the test suite."""
    builder = SampleModelBuilder(schema=schema)

    # --- L00: substructure + ground floor -------------------------------
    for index in range(4):
        builder.add_element(
            "IfcFooting",
            f"Pad Footing F{index + 1}",
            storey="L00",
            predefined_type="PAD_FOOTING",
            quantities={"NetVolume": 3.5, "GrossVolume": 3.6, "Count": 1},
            material="In-situ Concrete C32/40",
            classification=("Uniclass 2015", "Ss_20_05_15", "Pad foundation systems"),
        )
    builder.add_element(
        "IfcSlab",
        "Ground Bearing Slab",
        storey="L00",
        predefined_type="BASESLAB",
        quantities={"NetVolume": 90.0, "NetArea": 450.0, "Count": 1},
        material="In-situ Concrete C32/40",
    )

    # --- L01 / L02: superstructure --------------------------------------
    for storey in ("L01", "L02"):
        for index in range(6):
            builder.add_element(
                "IfcColumn",
                f"{storey} Column C{index + 1}",
                storey=storey,
                predefined_type="COLUMN",
                quantities={"NetVolume": 1.2, "Length": 3.5, "Count": 1},
                material="In-situ Concrete C40/50",
                type_name="400x400 RC Column",
            )
        builder.add_element(
            "IfcSlab",
            f"{storey} Floor Slab",
            storey=storey,
            predefined_type="FLOOR",
            quantities={"NetVolume": 67.5, "NetArea": 450.0, "Count": 1},
            material="In-situ Concrete C32/40",
        )
        for index in range(3):
            builder.add_element(
                "IfcBeam",
                f"{storey} Beam B{index + 1}",
                storey=storey,
                predefined_type="BEAM",
                quantities={"NetVolume": 2.1, "Length": 7.5, "Count": 1},
                material="In-situ Concrete C40/50",
            )

        # Two distinct wall materials so L3 and L4 differ.
        for index in range(4):
            builder.add_element(
                "IfcWall",
                f"{storey} External Wall EW{index + 1}",
                storey=storey,
                predefined_type="SOLIDWALL",
                quantities={"NetArea": 42.0, "NetVolume": 8.4, "Length": 12.0, "Count": 1},
                material="200mm Blockwork",
                type_name="200mm Blockwork",
                properties={"Pset_WallCommon": {"Sector": "North" if index < 2 else "South"}},
            )
        for index in range(5):
            builder.add_element(
                "IfcWall",
                f"{storey} Partition P{index + 1}",
                storey=storey,
                predefined_type="PARTITIONING",
                quantities={"NetArea": 18.0, "Length": 6.0, "Count": 1},
                material=["Plasterboard", "Steel Stud", "Plasterboard"],
                type_name="100mm Metal Stud Partition",
                properties={"Pset_WallCommon": {"Sector": "North" if index < 3 else "South"}},
            )

        for index in range(4):
            builder.add_element(
                "IfcWindow",
                f"{storey} Window W{index + 1}",
                storey=storey,
                predefined_type="WINDOW",
                quantities={"NetArea": 2.4, "Height": 1.5, "Width": 1.6, "Count": 1},
                material="Aluminium",
                type_name="1600x1500 Aluminium Window",
            )
        for index in range(3):
            builder.add_element(
                "IfcDoor",
                f"{storey} Door D{index + 1}",
                storey=storey,
                predefined_type="DOOR",
                quantities={"NetArea": 1.9, "Height": 2.1, "Width": 0.9, "Count": 1},
                material="Timber",
            )

        # MEP
        for index in range(3):
            builder.add_element(
                "IfcDuctSegment",
                f"{storey} Supply Duct DS{index + 1}",
                storey=storey,
                quantities={"Length": 24.0, "Count": 1},
                material="Galvanised Steel",
            )
        for index in range(2):
            builder.add_element(
                "IfcPipeSegment",
                f"{storey} CHW Pipe PS{index + 1}",
                storey=storey,
                quantities={"Length": 30.0, "Count": 1},
                material="Copper",
            )
        builder.add_element(
            "IfcFlowTerminal",
            f"{storey} Diffusers",
            storey=storey,
            quantities={"Count": 12},
            material="Steel",
        )

        # Finishes
        builder.add_element(
            "IfcCovering",
            f"{storey} Floor Finish",
            storey=storey,
            predefined_type="FLOORING",
            quantities={"NetArea": 420.0, "Count": 1},
            material="Vinyl",
        )
        builder.add_element(
            "IfcCovering",
            f"{storey} Ceiling",
            storey=storey,
            predefined_type="CEILING",
            quantities={"NetArea": 420.0, "Count": 1},
            material="Mineral Fibre Tile",
        )

    # --- noise that must never become tasks ------------------------------
    for index in range(40):
        builder.add_element(
            "IfcMechanicalFastener",
            f"Bolt M20-{index}",
            storey="L01",
            quantities={"Count": 1},
            material="Steel",
        )
    for index in range(8):
        builder.add_element("IfcDiscreteAccessory", f"Bracket {index}", storey="L01")
    for index in range(6):
        builder.add_element("IfcOpeningElement", f"Opening {index}", storey="L01")
    builder.add_element("IfcAnnotation", "Section marker", storey="L01")
    builder.add_element("IfcVirtualElement", "Virtual boundary", storey="L01")

    space = builder.add_element(
        "IfcSpace", "Office 01", storey="L01", quantities={"NetArea": 120.0}
    )
    builder.add_zone("Zone North", [space])

    # --- assembly: children must collapse into the parent -----------------
    builder.add_assembly(
        "Steel Frame Assembly SF-01",
        "L02",
        [
            {
                "ifc_class": "IfcMember",
                "name": "SF-01 Chord 1",
                "quantities": {"NetVolume": 0.4, "Length": 6.0, "Count": 1},
                "material": "Structural Steel S355",
            },
            {
                "ifc_class": "IfcMember",
                "name": "SF-01 Chord 2",
                "quantities": {"NetVolume": 0.4, "Length": 6.0, "Count": 1},
                "material": "Structural Steel S355",
            },
            {
                "ifc_class": "IfcPlate",
                "name": "SF-01 Gusset",
                "quantities": {"NetVolume": 0.02, "NetArea": 0.5, "Count": 1},
                "material": "Structural Steel S355",
            },
        ],
    )

    # --- size threshold cases ---------------------------------------------
    for index in range(5):
        builder.add_element(
            "IfcBuildingElementProxy",
            f"Tiny Bracket {index}",
            storey="L02",
            quantities={"NetVolume": 0.001, "Count": 1},
            material="Steel",
        )
    # A proxy big enough to keep, which the LLM classifier would improve on.
    builder.add_element(
        "IfcBuildingElementProxy",
        "Plant Skid PS-01",
        storey="L02",
        quantities={"NetVolume": 4.0, "Count": 1},
        object_type="Packaged Chiller Skid",
        material="Steel",
    )

    # --- no base quantities: forces the geometry fallback ------------------
    builder.add_element(
        "IfcColumn",
        "L02 Column C7 (no Qto)",
        storey="L02",
        predefined_type="COLUMN",
        material="In-situ Concrete C40/50",
        geometry=(0.4, 0.4, 3.5),
    )

    # --- kept, but with no quantities and no geometry ----------------------
    # These survive filtering (nothing proves they are trivial) but cannot
    # stand alone as L5 tasks, so they must aggregate.
    for storey in ("L01", "L02"):
        builder.add_element("IfcStair", f"{storey} Stair Core ST-01", storey=storey)

    # --- element with no spatial container at all --------------------------
    builder.add_element(
        "IfcRailing",
        "Orphan Balustrade",
        storey=None,
        quantities={"Length": 15.0, "Count": 1},
        material="Stainless Steel",
    )

    # --- name-pattern exclusion -------------------------------------------
    builder.add_element(
        "IfcWall", "DUMMY placeholder wall", storey="L02", quantities={"NetArea": 5.0}
    )

    return builder


def write_sample_ifc(path: str | Path, schema: str = "IFC4") -> Path:
    return build_sample_model(schema=schema).write(path)


if __name__ == "__main__":  # pragma: no cover
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "sample.ifc"
    print("wrote", write_sample_ifc(target))
