"""LOD grouping: all five levels, plus the optional zone split."""

from __future__ import annotations

import pandas as pd
import pytest

from app.schedule.lod import (
    LEVELS,
    group_elements,
    humanize_class,
    predict_task_counts,
    resolve_zone,
)
from app.schedule.work_packages import WorkPackageClassifier


@pytest.fixture
def kept(filtered):
    frame, _report = filtered
    return frame


def _labels(groups):
    return [group.label for group in groups]


# --- level semantics ------------------------------------------------------


def test_l1_is_one_task_per_storey(kept):
    groups = group_elements(kept, "L1")
    assert all(group.level == "L1" for group in groups)
    storeys = {group.storey_name for group in groups}
    assert storeys == {"L00", "L01", "L02", "Unassigned"}
    assert len(groups) == len(storeys)
    assert all(group.wbs_path[:2] for group in groups)


def test_l2_is_storey_by_work_package(kept):
    groups = group_elements(kept, "L2")
    assert "L01 – Superstructure" in _labels(groups)
    assert "L01 – MEP" in _labels(groups)
    keys = {(group.storey_name, group.work_package) for group in groups}
    assert len(keys) == len(groups)
    assert {group.work_package for group in groups} <= {
        "Substructure",
        "Superstructure",
        "Envelope",
        "MEP",
        "Interior",
        "Finishes",
    }


def test_l3_is_storey_by_class_and_is_the_default(kept):
    groups = group_elements(kept)
    assert all(group.level == "L3" for group in groups)
    labels = _labels(groups)
    assert "L01 – Columns" in labels
    assert "L01 – Floor Slabs" in labels
    assert "L00 – Pad Footings" in labels
    # Blockwork and stud walls share IfcWall but differ by PredefinedType.
    assert "L01 – Solid Walls" in labels
    assert "L01 – Partitions" in labels


def test_l4_splits_by_type_or_material(kept):
    l3 = group_elements(kept, "L3")
    l4 = group_elements(kept, "L4")
    assert len(l4) >= len(l3)
    assert "L01 – 200mm Blockwork Solid Walls" in _labels(l4)
    assert "L01 – 100mm Metal Stud Partitions" in _labels(l4)


def test_l5_is_one_task_per_measurable_element(kept):
    groups = group_elements(kept, "L5")
    element_ids = [element_id for group in groups for element_id in group.element_ids]
    assert len(element_ids) == len(kept)
    assert len(set(element_ids)) == len(element_ids)
    individual = [group for group in groups if group.level == "L5"]
    assert all(group.element_count == 1 for group in individual)


def test_l5_aggregates_elements_that_cannot_stand_alone(kept):
    groups = group_elements(kept, "L5")
    aggregated = [group for group in groups if group.aggregated_trivial]
    assert aggregated, "expected unmeasurable elements to be folded up"
    for group in aggregated:
        assert group.level == "L4"
        assert group.notes


def test_l5_aggregation_can_be_switched_off(kept):
    config = {"aggregate_trivial_at_l5": False, "size_threshold": {"enabled": True}}
    groups = group_elements(kept, "L5", filters_config=config)
    assert all(group.level == "L5" for group in groups)
    assert len(groups) == len(kept)


# --- element conservation -------------------------------------------------


@pytest.mark.parametrize("level", LEVELS)
def test_every_element_lands_in_exactly_one_group(kept, level):
    groups = group_elements(kept, level)
    seen = [element_id for group in groups for element_id in group.element_ids]
    assert sorted(seen) == sorted(kept.global_id.tolist())


@pytest.mark.parametrize("level", LEVELS)
def test_quantities_are_summed_into_the_group(kept, level):
    groups = group_elements(kept, level)
    total = sum(group.quantities.get("NetVolume", 0.0) for group in groups)
    assert total == pytest.approx(kept.qty_NetVolume.fillna(0).sum())
    assert all(group.quantities["Count"] == group.element_count for group in groups)


@pytest.mark.parametrize("level", LEVELS)
def test_grouping_is_deterministic(kept, level):
    first = group_elements(kept, level)
    second = group_elements(kept, level)
    assert _labels(first) == _labels(second)
    assert [group.element_ids for group in first] == [group.element_ids for group in second]


def test_task_counts_increase_with_detail(kept):
    counts = {
        level: len(group_elements(kept, level))
        for level in LEVELS
    }
    assert counts["L1"] < counts["L2"] < counts["L3"] <= counts["L4"] < counts["L5"]


# --- zone split -----------------------------------------------------------


def test_pset_zone_split_subdivides_groups(kept):
    without = group_elements(kept, "L3")
    with_zone = group_elements(kept, "L3", zone_split="Pset_WallCommon.Sector")
    assert len(with_zone) > len(without)
    labels = _labels(with_zone)
    assert any("[North]" in label for label in labels)
    assert any("[South]" in label for label in labels)
    zoned = [group for group in with_zone if group.zone_name]
    assert all(group.wbs_path[3] == group.zone_name for group in zoned)


def test_zone_split_still_conserves_elements(kept):
    groups = group_elements(kept, "L3", zone_split="Pset_WallCommon.Sector")
    seen = [element_id for group in groups for element_id in group.element_ids]
    assert sorted(seen) == sorted(kept.global_id.tolist())


def test_resolve_zone_handles_all_sources():
    row = {"zone_name": "Zone North", "property_sets": {"Pset_X": {"Sector": "S1", "Phase": ""}}}
    assert resolve_zone(row, None) is None
    assert resolve_zone(row, "zone") == "Zone North"
    assert resolve_zone(row, "Pset_X.Sector") == "S1"
    assert resolve_zone(row, "Pset_X.Phase") is None
    assert resolve_zone(row, "Pset_X.Missing") is None
    assert resolve_zone(row, "Sector") == "S1"
    assert resolve_zone({}, "Pset_X.Sector") is None


# --- misc -----------------------------------------------------------------


def test_predict_task_counts_covers_every_level(kept):
    predictions = predict_task_counts(kept, None, WorkPackageClassifier())
    assert [item["level"] for item in predictions] == list(LEVELS)
    assert next(item for item in predictions if item["is_default"])["level"] == "L3"
    for item in predictions:
        assert item["task_count"] == len(group_elements(kept, item["level"]))


def test_unknown_level_is_rejected(kept):
    with pytest.raises(ValueError, match="unknown level of detail"):
        group_elements(kept, "L9")


def test_humanize_avoids_duplicate_and_redundant_labels():
    assert humanize_class("IfcColumn", "COLUMN") == "Columns"
    assert humanize_class("IfcSlab", "FLOOR") == "Floor Slabs"
    assert humanize_class("IfcCovering", "CEILING") == "Ceilings"
    assert humanize_class("IfcCovering", "FLOORING") == "Floor Finishes"
    assert humanize_class("IfcBeam", "NOTDEFINED") == "Beams"
    assert humanize_class("IfcChimney") == "Chimneys"


def test_labels_are_unique_within_a_level(kept):
    for level in LEVELS:
        labels = _labels(group_elements(kept, level))
        assert len(labels) == len(set(labels)), f"duplicate labels at {level}"


def test_empty_frame_yields_no_groups():
    assert group_elements(pd.DataFrame(), "L3") == []
