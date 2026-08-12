"""Duration engine: the formula, the fallback chain, and confidence."""

from __future__ import annotations

import pytest

from app.schedule.durations import RateLibrary, compute_duration
from app.schedule.lod import TaskGroup, group_elements


def make_group(**overrides) -> TaskGroup:
    defaults = dict(
        key=("k",),
        label="Test group",
        level="L3",
        wbs_path=["Site", "Building", "L01"],
        work_package="Superstructure",
        storey_id="s1",
        storey_name="L01",
        storey_elevation=3.5,
        zone_name=None,
        ifc_class="IfcColumn",
        predefined_type="COLUMN",
        type_name=None,
        material="In-situ Concrete C40/50",
        element_ids=["a"],
        element_count=1,
        quantities={"NetVolume": 12.0, "Count": 1.0},
        quantity_source="base_quantity",
    )
    defaults.update(overrides)
    return TaskGroup(**defaults)


SIMPLE_LIBRARY = {
    "default": {
        "unit": "ea",
        "output_per_crew_day": 10.0,
        "default_crew": 1,
        "min_duration_days": 1,
    },
    "count_fallback": {
        "unit": "ea",
        "output_per_crew_day": 20.0,
        "default_crew": 1,
        "min_duration_days": 1,
    },
    "rules": [
        {
            "id": "column-concrete",
            "match": {"ifc_class": "IfcColumn", "material_pattern": "(?i)concrete"},
            "unit": "m3",
            "output_per_crew_day": 6.0,
            "default_crew": 2,
            "min_duration_days": 2,
        },
        {
            "id": "column-any",
            "match": {"ifc_class": "IfcColumn"},
            "unit": "m3",
            "output_per_crew_day": 5.0,
            "default_crew": 2,
            "min_duration_days": 2,
        },
        {
            "id": "wall-area-only",
            "match": {"ifc_class": "IfcWall"},
            "unit": "m2",
            "output_per_crew_day": 10.0,
            "default_crew": 1,
            "min_duration_days": 1,
        },
    ],
}


# --- the formula ----------------------------------------------------------


def test_duration_is_ceil_of_quantity_over_rate_times_crew():
    library = RateLibrary(SIMPLE_LIBRARY)
    result = compute_duration(make_group(quantities={"NetVolume": 25.0}), library)
    # 25 / (6.0 * 2) = 2.083 -> ceil -> 3
    assert result.duration_days == 3
    assert result.rate_id == "column-concrete"
    assert result.unit == "m3"
    assert result.quantity == 25.0
    assert result.quantity_key == "NetVolume"


def test_duration_is_clamped_to_the_minimum():
    library = RateLibrary(SIMPLE_LIBRARY)
    result = compute_duration(make_group(quantities={"NetVolume": 0.5}), library)
    # 0.5 / 12 rounds up to 1 day, but the rule's floor is 2.
    assert result.duration_days == 2


def test_crew_override_shortens_the_task():
    library = RateLibrary(SIMPLE_LIBRARY)
    base = compute_duration(make_group(quantities={"NetVolume": 60.0}), library)
    boosted = compute_duration(
        make_group(quantities={"NetVolume": 60.0}), library, crew_overrides={"column-concrete": 10}
    )
    assert base.duration_days == 5  # 60 / 12
    assert boosted.duration_days == 2  # 60 / 60 -> 1, floored at min 2
    assert boosted.crew == 10


# --- the fallback chain ---------------------------------------------------


def test_type_specific_rate_wins_and_scores_high_confidence():
    library = RateLibrary(SIMPLE_LIBRARY)
    result = compute_duration(make_group(), library)
    assert result.rate_id == "column-concrete"
    assert result.rate_source == "type_rate"
    assert result.confidence == "high"


def test_falls_back_to_the_class_rate_when_material_does_not_match():
    library = RateLibrary(SIMPLE_LIBRARY)
    result = compute_duration(make_group(material="Structural Steel S355"), library)
    assert result.rate_id == "column-any"
    assert result.rate_source == "class_rate"
    assert result.confidence == "medium"


def test_falls_back_to_the_global_default_for_an_unknown_class():
    library = RateLibrary(SIMPLE_LIBRARY)
    result = compute_duration(
        make_group(ifc_class="IfcTendon", material=None, quantities={"Count": 30.0}), library
    )
    assert result.rate_id == "default"
    assert result.rate_source == "global_default"
    assert result.confidence == "low"
    assert result.duration_days == 3  # 30 / 10


def test_falls_back_to_counting_when_the_rule_unit_has_no_quantity():
    library = RateLibrary(SIMPLE_LIBRARY)
    # An IfcWall rule needs m2; this group only has a count.
    result = compute_duration(
        make_group(ifc_class="IfcWall", predefined_type=None, quantities={"Count": 40.0}),
        library,
    )
    assert result.unit == "ea"
    assert result.confidence == "low"
    assert any("no m2 quantity" in note for note in result.notes)


def test_group_with_no_quantities_at_all_still_produces_a_duration():
    library = RateLibrary(SIMPLE_LIBRARY)
    result = compute_duration(make_group(quantities={}, quantity_source="none"), library)
    assert result.duration_days >= 1
    assert result.confidence == "low"


# --- confidence -----------------------------------------------------------


def test_derived_quantities_downgrade_a_high_confidence_match():
    library = RateLibrary(SIMPLE_LIBRARY)
    result = compute_duration(make_group(quantity_source="derived"), library)
    assert result.rate_source == "type_rate"
    assert result.confidence == "medium"
    assert any("geometry-derived" in note for note in result.notes)


def test_unmeasured_group_is_always_low_confidence():
    library = RateLibrary(SIMPLE_LIBRARY)
    result = compute_duration(
        make_group(quantity_source="none", quantities={"Count": 4.0}), library
    )
    assert result.confidence == "low"


# --- library loading ------------------------------------------------------


def test_packaged_library_loads_and_matches_real_groups(filtered):
    kept, _ = filtered
    library = RateLibrary()
    assert library.rules
    for group in group_elements(kept, "L3"):
        result = compute_duration(group, library)
        assert result.duration_days >= 1
        assert result.confidence in ("high", "medium", "low")
        assert result.unit in ("m3", "m2", "m", "ea")


def test_invalid_rules_are_skipped_not_fatal():
    library = RateLibrary(
        {
            "rules": [
                {"id": "bad-unit", "match": {"ifc_class": "IfcWall"}, "unit": "furlongs"},
                {"id": "bad-regex", "match": {"ifc_class": "IfcWall", "material_pattern": "([",},
                 "unit": "m2", "output_per_crew_day": 5.0},
            ]
        }
    )
    assert [rate.id for rate in library.rules] == ["bad-regex"]
    assert library.rules[0].material_regex is None


def test_zero_output_rate_is_skipped():
    library = RateLibrary(
        {
            "rules": [
                {
                    "id": "broken",
                    "match": {"ifc_class": "IfcColumn"},
                    "unit": "m3",
                    "output_per_crew_day": 0,
                    "default_crew": 1,
                }
            ],
            "default": {"unit": "ea", "output_per_crew_day": 10.0, "default_crew": 1},
        }
    )
    result = compute_duration(make_group(quantities={"NetVolume": 10.0, "Count": 5.0}), library)
    assert result.rate_id != "broken"
    assert result.duration_days >= 1


def test_rate_library_round_trips_to_dict():
    payload = RateLibrary(SIMPLE_LIBRARY).as_dict()
    assert payload["default"]["unit"] == "ea"
    assert {rule["id"] for rule in payload["rules"]} == {
        "column-concrete",
        "column-any",
        "wall-area-only",
    }
    concrete = next(r for r in payload["rules"] if r["id"] == "column-concrete")
    assert concrete["material_pattern"] == "(?i)concrete"


@pytest.mark.parametrize(
    ("quantity", "expected"),
    [(1.0, 2), (12.0, 2), (13.0, 2), (24.0, 2), (25.0, 3), (120.0, 10)],
)
def test_duration_curve(quantity, expected):
    library = RateLibrary(SIMPLE_LIBRARY)
    result = compute_duration(make_group(quantities={"NetVolume": quantity}), library)
    assert result.duration_days == expected
