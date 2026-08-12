"""End-to-end pipeline and the per-run report."""

from __future__ import annotations

import pandas as pd
import pytest

from app.schedule.lod import LEVELS
from app.schedule.pipeline import ScheduleOptions, generate_schedule


@pytest.fixture(scope="module")
def schedule(request):
    frame = request.getfixturevalue("elements")
    return generate_schedule(frame, ScheduleOptions(level="L3", start_date="2026-09-01"))


def test_pipeline_produces_a_calculated_schedule(schedule):
    assert schedule.tasks
    assert schedule.links
    for task in schedule.tasks:
        assert task["id"]
        assert task["label"]
        assert task["duration_days"] >= 1
        assert task["start_date"] <= task["finish_date"]
        assert task["confidence"] in ("high", "medium", "low")
        assert isinstance(task["is_critical"], bool)
        assert task["element_ids"]
        assert task["element_count"] == len(task["element_ids"])


def test_every_task_keeps_its_source_global_ids(schedule, elements):
    known = set(elements.global_id)
    seen: list[str] = []
    for task in schedule.tasks:
        assert set(task["element_ids"]) <= known
        seen.extend(task["element_ids"])
    assert len(seen) == len(set(seen)), "an element appears in two tasks"


def test_task_ids_are_unique_and_stable(elements):
    first = generate_schedule(elements, ScheduleOptions(level="L3", start_date="2026-09-01"))
    second = generate_schedule(elements, ScheduleOptions(level="L3", start_date="2026-09-01"))
    ids = [task["id"] for task in first.tasks]
    assert len(ids) == len(set(ids))
    assert ids == [task["id"] for task in second.tasks]


def test_wbs_codes_are_unique(schedule):
    codes = [task["wbs_code"] for task in schedule.tasks]
    assert all(codes)
    assert len(codes) == len(set(codes))


def test_critical_path_exists_and_spans_the_project(schedule):
    critical = [task for task in schedule.tasks if task["is_critical"]]
    assert critical
    assert all(task["total_float"] <= 0 for task in critical)
    duration = schedule.report["cpm"]["project_duration_days"]
    assert max(task["early_finish_offset"] for task in schedule.tasks) == duration


def test_links_reference_real_tasks(schedule):
    ids = {task["id"] for task in schedule.tasks}
    for link in schedule.links:
        assert link["predecessor_id"] in ids
        assert link["successor_id"] in ids
        assert link["type"] in ("FS", "SS", "FF", "SF")
        assert link["origin"]


def test_predecessors_are_mirrored_onto_tasks(schedule):
    from_links = {
        (link["predecessor_id"], link["successor_id"]) for link in schedule.links
    }
    from_tasks = {
        (link["id"], task["id"]) for task in schedule.tasks for link in task["predecessors"]
    }
    assert from_links == from_tasks


# --- the run report -------------------------------------------------------


def test_run_report_accounts_for_every_element(schedule, elements):
    report = schedule.report
    filter_report = report["filter"]
    assert filter_report["elements_in"] == len(elements)
    assert filter_report["elements_kept"] + filter_report["elements_removed"] == len(elements)
    assert report["grouping"]["elements_in_tasks"] == filter_report["elements_kept"]
    assert filter_report["removed_by_reason"]


def test_run_report_covers_all_stages(schedule):
    report = schedule.report
    assert set(report) >= {"parse", "filter", "grouping", "durations", "sequencing", "cpm"}
    assert report["durations"]["quantity_coverage_pct"] > 0
    assert sum(report["durations"]["confidence"].values()) == len(schedule.tasks)
    assert report["sequencing"]["link_count"] == len(schedule.links)
    assert report["sequencing"]["by_origin"]
    assert report["cpm"]["project_duration_days"] > 0
    assert not report["cpm"]["cycles_broken"]
    assert not report["cpm"]["dropped_links"]


# --- options --------------------------------------------------------------


@pytest.mark.parametrize("level", LEVELS)
def test_every_level_runs_end_to_end(elements, level):
    result = generate_schedule(elements, ScheduleOptions(level=level, start_date="2026-09-01"))
    assert result.tasks
    assert result.report["grouping"]["level"] == level
    assert result.report["cpm"]["project_duration_days"] > 0


def test_zone_split_flows_through_to_the_tasks(elements):
    result = generate_schedule(
        elements,
        ScheduleOptions(level="L3", zone_split="Pset_WallCommon.Sector", start_date="2026-09-01"),
    )
    zones = {task["zone_name"] for task in result.tasks if task["zone_name"]}
    assert zones == {"North", "South"}
    assert result.report["grouping"]["zone_split"] == "Pset_WallCommon.Sector"


def test_calendar_options_are_honoured(elements):
    result = generate_schedule(
        elements,
        ScheduleOptions(
            level="L2",
            start_date="2026-09-07",
            work_days=[0, 1, 2, 3, 4, 5],
            holidays=["2026-09-09"],
        ),
    )
    assert result.calendar["start_date"] == "2026-09-07"
    assert result.calendar["days_per_week"] == 6
    assert "2026-09-09" in result.calendar["holidays"]
    assert all(task["start_date"] != "2026-09-09" for task in result.tasks)


def test_crew_override_shortens_the_programme(elements):
    base = generate_schedule(elements, ScheduleOptions(level="L3", start_date="2026-09-01"))
    faster = generate_schedule(
        elements,
        ScheduleOptions(
            level="L3", start_date="2026-09-01", crew_overrides={"wall-blockwork": 20}
        ),
    )
    wall = next(t for t in faster.tasks if t["rate_id"] == "wall-blockwork")
    base_wall = next(t for t in base.tasks if t["rate_id"] == "wall-blockwork")
    assert wall["crew"] == 20
    assert wall["duration_days"] < base_wall["duration_days"]


def test_rate_overrides_change_durations(elements):
    options = ScheduleOptions(level="L3", start_date="2026-09-01")
    base = generate_schedule(elements, options)
    options.rate_overrides = {"rules": [{"id": "wall-blockwork", "output_per_crew_day": 1.0}]}
    slower = generate_schedule(elements, options)
    slow_wall = next(t for t in slower.tasks if t["rate_id"] == "wall-blockwork")
    base_wall = next(t for t in base.tasks if t["rate_id"] == "wall-blockwork")
    assert slow_wall["duration_days"] > base_wall["duration_days"]


def test_llm_layer_is_off_by_default_and_never_required(elements, monkeypatch):
    monkeypatch.setenv("IFCSCHED_LLM_ENABLED", "false")
    deterministic = generate_schedule(
        elements, ScheduleOptions(level="L3", start_date="2026-09-01")
    )
    # Asking for enrichment with the layer disabled must change nothing.
    requested = generate_schedule(
        elements, ScheduleOptions(level="L3", start_date="2026-09-01", llm_enabled=True)
    )
    assert [t["label"] for t in deterministic.tasks] == [t["label"] for t in requested.tasks]
    assert [t["duration_days"] for t in deterministic.tasks] == [
        t["duration_days"] for t in requested.tasks
    ]


def test_empty_frame_is_rejected_cleanly():
    result = generate_schedule(pd.DataFrame(), ScheduleOptions(level="L3"))
    assert result.tasks == []
    assert result.links == []
    assert result.report["grouping"]["task_count"] == 0


def test_options_round_trip():
    options = ScheduleOptions.from_dict(
        {"level": "l4", "zone_split": "zone", "crew_overrides": {"a": "3"}}
    )
    assert options.level == "L4"
    assert options.crew_overrides == {"a": 3}
    assert options.as_dict()["zone_split"] == "zone"
