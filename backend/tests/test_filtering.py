"""Noise filtering: nuts and bolts must never reach the schedule."""

from __future__ import annotations

import pandas as pd
import pytest

from app.schedule.filtering import (
    REASON_ASSEMBLY_CHILD,
    REASON_BELOW_SIZE,
    REASON_EXCLUDED_CLASS,
    REASON_NAME_PATTERN,
    ElementFilter,
)


def test_excluded_classes_are_removed(filtered):
    kept, report = filtered
    remaining = set(kept.ifc_class)
    for excluded in (
        "IfcMechanicalFastener",
        "IfcDiscreteAccessory",
        "IfcOpeningElement",
        "IfcAnnotation",
        "IfcVirtualElement",
        "IfcSpace",
    ):
        assert excluded not in remaining
    assert report.by_reason[REASON_EXCLUDED_CLASS] >= 40


def test_subclasses_of_an_excluded_class_are_also_removed():
    """Exclusions match on the whole class hierarchy, not the leaf name."""
    element_filter = ElementFilter()
    element_filter.excluded_classes = ["IfcElementComponent"]
    element_filter.overrides = {}
    assert not element_filter.is_class_schedulable(
        "IfcMechanicalFastener",
        ["IfcMechanicalFastener", "IfcElementComponent", "IfcElement"],
    )
    assert element_filter.is_class_schedulable("IfcWall", ["IfcWall", "IfcBuildingElement"])


def test_schedulable_override_wins_over_the_exclusion_list():
    element_filter = ElementFilter(
        {"excluded_classes": ["IfcFurniture"], "schedulable_overrides": {"IfcFurniture": True}}
    )
    assert element_filter.is_class_schedulable("IfcFurniture", ["IfcFurniture", "IfcElement"])

    element_filter = ElementFilter(
        {"excluded_classes": [], "schedulable_overrides": {"IfcSpace": False}}
    )
    assert not element_filter.is_class_schedulable("IfcSpace", ["IfcSpace"])


def test_assembly_children_collapse_into_the_parent(filtered, classified):
    kept, report = filtered
    assembly = classified[classified.is_assembly].iloc[0]
    assert assembly.global_id in set(kept.global_id)
    assert not any(kept.assembly_id == assembly.global_id)
    assert report.by_reason[REASON_ASSEMBLY_CHILD] == 3


def test_assembly_children_survive_when_collapsing_is_off(classified):
    element_filter = ElementFilter(
        {"collapse_assemblies": False, "size_threshold": {"enabled": False}}
    )
    kept, report = element_filter.apply(classified)
    assert REASON_ASSEMBLY_CHILD not in report.by_reason
    assert (kept.assembly_id.notna()).sum() == 3


def test_tiny_elements_are_rolled_up_not_scheduled(filtered):
    kept, report = filtered
    assert "Tiny Bracket 0" not in set(kept.name)
    assert report.by_reason[REASON_BELOW_SIZE] == 5
    # The rolled-up quantity is retained so nothing silently vanishes.
    assert report.rolled_up_quantity["Count"] == 5
    assert report.rolled_up_quantity["NetVolume"] == pytest.approx(0.005)


def test_size_threshold_never_drops_protected_classes(filtered):
    kept, _ = filtered
    # Doors and windows are small but always schedulable.
    assert (kept.ifc_class == "IfcDoor").sum() == 6
    assert (kept.ifc_class == "IfcWindow").sum() == 8


def test_element_with_no_measurement_is_not_size_filtered():
    element_filter = ElementFilter()
    row = {
        "ifc_class": "IfcWall",
        "class_hierarchy": ["IfcWall", "IfcElement"],
        "qty_NetVolume": None,
        "quantities": {},
    }
    assert not element_filter.is_below_size(row)


def test_name_patterns_are_applied(filtered):
    kept, report = filtered
    assert "DUMMY placeholder wall" not in set(kept.name)
    assert report.by_reason[REASON_NAME_PATTERN] == 1


def test_report_accounts_for_every_element(filtered):
    kept, report = filtered
    assert report.total_in == report.kept + report.removed
    assert report.kept == len(kept)
    payload = report.as_dict()
    assert payload["elements_kept"] == len(kept)
    assert set(payload["removed_by_reason"]) <= {
        REASON_EXCLUDED_CLASS,
        REASON_NAME_PATTERN,
        REASON_ASSEMBLY_CHILD,
        REASON_BELOW_SIZE,
    }
    for reason, examples in payload["examples"].items():
        assert examples, f"{reason} recorded no example ids"


def test_empty_frame_is_handled():
    kept, report = ElementFilter().apply(pd.DataFrame())
    assert kept.empty
    assert report.total_in == 0
