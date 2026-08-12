"""Parser: extraction correctness and graceful degradation."""

from __future__ import annotations

import pytest

from app.ifc.model import records_to_frame
from app.ifc.parser import class_hierarchy, parse_ifc


def test_reads_the_expected_shape(parse_report, elements):
    assert parse_report.schema == "IFC4"
    assert parse_report.elements_read == len(elements)
    assert parse_report.elements_read > 100
    # Site, building and three storeys are context, not elements.
    assert parse_report.skipped_spatial == 5
    assert not parse_report.errors


def test_storey_and_elevation_are_resolved(elements):
    columns = elements[elements.ifc_class == "IfcColumn"]
    assert set(columns.storey_name.dropna()) == {"L01", "L02"}
    elevations = dict(zip(elements.storey_name, elements.storey_elevation, strict=False))
    assert elevations["L00"] == pytest.approx(0.0)
    assert elevations["L01"] == pytest.approx(3.5)
    assert elevations["L02"] == pytest.approx(7.0)


def test_base_quantities_are_read_in_si(elements):
    slab = elements[elements.name == "Ground Bearing Slab"].iloc[0]
    assert slab.qty_NetVolume == pytest.approx(90.0)
    assert slab.qty_NetArea == pytest.approx(450.0)
    assert slab.quantity_source == "base_quantity"


def test_type_material_and_classification(elements):
    column = elements[elements.name == "L01 Column C1"].iloc[0]
    assert column.type_name == "400x400 RC Column"
    assert column.material == "In-situ Concrete C40/50"
    assert column.material_kind == "single"

    partition = elements[elements.name == "L01 Partition P1"].iloc[0]
    assert partition.material_kind == "layered"
    assert "Plasterboard" in (partition.material or "")

    footing = elements[elements.name == "Pad Footing F1"].iloc[0]
    assert footing.classification.startswith("Ss_20_05_15")
    assert footing.classification_system == "Uniclass 2015"


def test_property_sets_are_captured_for_zone_splitting(elements):
    wall = elements[elements.name == "L01 External Wall EW1"].iloc[0]
    assert wall.property_sets["Pset_WallCommon"]["Sector"] == "North"


def test_geometry_fallback_populates_quantities(elements):
    derived = elements[elements.name == "L02 Column C7 (no Qto)"].iloc[0]
    assert derived.quantity_source == "derived"
    # 0.4 x 0.4 x 3.5 extrusion
    assert derived.qty_NetVolume == pytest.approx(0.56, rel=0.02)
    assert derived.quantities["BBoxDiagonal"] == pytest.approx(3.545, rel=0.02)


def test_assembly_quantities_roll_up_to_the_parent(elements):
    assembly = elements[elements.is_assembly].iloc[0]
    # 0.4 + 0.4 + 0.02 from the three children
    assert assembly.qty_NetVolume == pytest.approx(0.82)
    children = elements[elements.assembly_id == assembly.global_id]
    assert len(children) == 3


def test_element_without_a_container_is_still_read(elements):
    orphan = elements[elements.name == "Orphan Balustrade"].iloc[0]
    assert orphan.storey_name is None
    assert orphan.qty_Length == 15.0


def test_class_hierarchy_supports_is_a_after_close(elements):
    fastener = elements[elements.ifc_class == "IfcMechanicalFastener"].iloc[0]
    # In IFC4 IfcMechanicalFastener is a sibling of IfcFastener, both under
    # IfcElementComponent -- which is exactly why the filter matches on the
    # recorded hierarchy rather than on the leaf class name.
    assert fastener.class_hierarchy[0] == "IfcMechanicalFastener"
    assert "IfcElementComponent" in fastener.class_hierarchy
    assert "IfcElement" in fastener.class_hierarchy

    wall = elements[elements.ifc_class == "IfcWall"].iloc[0]
    assert "IfcBuildingElement" in wall.class_hierarchy
    assert class_hierarchy("IFC4", "IfcWall")[0] == "IfcWall"
    # Unknown classes degrade to a single-entry chain rather than raising.
    assert class_hierarchy("IFC4", "IfcNotARealClass") == ["IfcNotARealClass"]


def test_bad_file_is_reported_not_raised(tmp_path):
    broken = tmp_path / "broken.ifc"
    broken.write_text("this is definitely not an IFC file")
    records, report = parse_ifc(broken)
    assert records == []
    assert report.errors
    assert report.elements_read == 0


def test_empty_file_produces_an_empty_frame(tmp_path):
    empty = tmp_path / "empty.ifc"
    empty.write_text("")
    records, report = parse_ifc(empty)
    frame = records_to_frame(records)
    assert frame.empty
    assert report.errors


def test_ifc2x3_is_supported(tmp_path):
    from tests.fixtures.sample_ifc import SampleModelBuilder

    builder = SampleModelBuilder(schema="IFC2X3")
    builder.add_element(
        "IfcColumn",
        "2X3 Column",
        storey="L01",
        quantities={"NetVolume": 1.5, "Count": 1},
        material="Concrete",
    )
    path = builder.write(tmp_path / "sample2x3.ifc")

    records, report = parse_ifc(path)
    assert report.schema == "IFC2X3"
    assert report.elements_read == 1
    assert records[0].storey_name == "L01"
    assert records[0].quantities["NetVolume"] == pytest.approx(1.5)
    assert records[0].material == "Concrete"


def test_quantity_coverage_is_reported(parse_report):
    coverage = parse_report.quantity_coverage()
    assert 0 < coverage <= 100
    assert parse_report.as_dict()["quantity_coverage_pct"] == coverage
