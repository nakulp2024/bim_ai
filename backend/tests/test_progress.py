"""Progress, baseline variance and the forecast pass."""

from __future__ import annotations

from datetime import date

import pytest

from app.schedule.calendar import WorkCalendar
from app.schedule.cpm import CpmTask, calculate
from app.schedule.progress import (
    FLAG_AHEAD,
    FLAG_BEHIND,
    FLAG_COMPLETE,
    FLAG_NOT_STARTED,
    FLAG_ON_TRACK,
    STATUS_COMPLETE,
    STATUS_IN_PROGRESS,
    STATUS_NOT_STARTED,
    ProgressEntry,
    evaluate_progress,
    planned_percent_at,
    resolve_state,
    snapshot_baseline,
)

# Tuesday 1 Sept 2026 on a Mon-Fri calendar.
START = "2026-09-01"


@pytest.fixture
def calendar():
    return WorkCalendar(start_date=START)


def make_schedule(calendar):
    """A (3d) -> B (4d) -> C (2d), all FS, with quantities on A and B.

    Planned: A 1-3 Sep, B 4-9 Sep, C 10-11 Sep.
    """
    tasks = [
        {"id": "A", "label": "A", "duration_days": 3, "quantity": 30.0, "unit": "m3"},
        {"id": "B", "label": "B", "duration_days": 4, "quantity": 400.0, "unit": "m2"},
        {"id": "C", "label": "C", "duration_days": 2, "quantity": None, "unit": "ea"},
    ]
    links = [
        {"predecessor_id": "A", "successor_id": "B", "type": "FS", "lag": 0},
        {"predecessor_id": "B", "successor_id": "C", "type": "FS", "lag": 0},
    ]
    offset = 0
    for task in tasks:
        task["early_start_offset"] = offset
        task["start_date"] = calendar.date_for_offset(offset).isoformat()
        task["finish_date"] = calendar.finish_date(offset, task["duration_days"]).isoformat()
        offset += task["duration_days"]
    return tasks, links


def by_id(result):
    return {row["id"]: row for row in result.tasks}


# --- CPM constraints -------------------------------------------------------


def test_pinned_start_overrides_predecessor_logic():
    result = calculate(
        [CpmTask("A", 5), CpmTask("B", 2, [{"id": "A", "type": "FS", "lag": 0}], pinned_start=2)]
    )
    # Logic says 5; it actually started on 2.
    assert result.tasks["B"].early_start == 2


def test_constraint_offset_is_a_floor_not_an_override():
    result = calculate(
        [
            CpmTask("A", 5),
            CpmTask("B", 2, [{"id": "A", "type": "FS", "lag": 0}], constraint_offset=3),
            CpmTask("C", 2, constraint_offset=8),
        ]
    )
    assert result.tasks["B"].early_start == 5  # logic wins when it is later
    assert result.tasks["C"].early_start == 8  # the floor wins when it is later


def test_complete_work_has_no_float_and_is_never_critical():
    result = calculate(
        [
            CpmTask("A", 2, complete=True, pinned_start=0),
            CpmTask("B", 3, [{"id": "A", "type": "FS", "lag": 0}]),
        ]
    )
    assert result.tasks["A"].total_float == 0
    assert not result.tasks["A"].is_critical
    assert result.tasks["B"].is_critical
    assert "A" not in result.critical_path


def test_existing_behaviour_unchanged_without_constraints():
    result = calculate([CpmTask("A", 3), CpmTask("B", 2, [{"id": "A", "type": "FS", "lag": 0}])])
    assert result.tasks["B"].early_start == 3
    assert result.tasks["A"].is_critical


# --- calendar inverse ------------------------------------------------------


def test_offset_for_date_is_the_inverse_of_date_for_offset(calendar):
    for offset in range(0, 40):
        assert calendar.offset_for_date(calendar.date_for_offset(offset)) == offset


def test_weekend_maps_to_the_next_working_day(calendar):
    # Sat 5 Sep -> Mon 7 Sep, which is offset 4.
    assert calendar.offset_for_date("2026-09-05") == 4
    assert calendar.offset_for_date("2026-09-07") == 4


def test_dates_before_the_start_are_negative(calendar):
    assert calendar.offset_for_date("2026-08-31") == -1
    assert calendar.working_days_between("2026-09-07", "2026-09-01") == -4


# --- resolving raw entries ------------------------------------------------


def test_quantity_derives_percent(calendar):
    tasks, _ = make_schedule(calendar)
    state = resolve_state(
        tasks[0], ProgressEntry("A", quantity_placed=15.0), date(2026, 9, 3), calendar
    )
    assert state["percent_complete"] == 50.0
    assert state["status"] == STATUS_IN_PROGRESS
    assert "percent complete derived from quantity placed" in state["progress_assumptions"]


def test_percent_derives_quantity(calendar):
    tasks, _ = make_schedule(calendar)
    state = resolve_state(
        tasks[1], ProgressEntry("B", percent_complete=25.0), date(2026, 9, 5), calendar
    )
    assert state["quantity_placed"] == 100.0


def test_reported_percent_wins_but_disagreement_is_flagged(calendar):
    tasks, _ = make_schedule(calendar)
    state = resolve_state(
        tasks[0],
        ProgressEntry("A", percent_complete=80.0, quantity_placed=6.0),
        date(2026, 9, 3),
        calendar,
    )
    assert state["percent_complete"] == 80.0
    assert any("disagrees" in note for note in state["progress_assumptions"])


def test_completion_fills_in_missing_dates(calendar):
    tasks, _ = make_schedule(calendar)
    state = resolve_state(
        tasks[0], ProgressEntry("A", percent_complete=100.0), date(2026, 9, 8), calendar
    )
    assert state["status"] == STATUS_COMPLETE
    assert state["actual_start"] == "2026-09-01"  # planned start
    assert state["actual_finish"] == "2026-09-07"  # working day before data date
    assert state["remaining_duration"] == 0
    assert state["quantity_placed"] == 30.0


def test_actual_finish_alone_means_complete(calendar):
    tasks, _ = make_schedule(calendar)
    state = resolve_state(
        tasks[0], ProgressEntry("A", actual_finish=date(2026, 9, 3)), date(2026, 9, 8), calendar
    )
    assert state["status"] == STATUS_COMPLETE
    assert state["percent_complete"] == 100.0


def test_in_progress_always_has_remaining_work(calendar):
    tasks, _ = make_schedule(calendar)
    state = resolve_state(
        tasks[1], ProgressEntry("B", percent_complete=99.0), date(2026, 9, 8), calendar
    )
    assert state["remaining_duration"] == 1


def test_remaining_duration_scales_with_percent(calendar):
    tasks, _ = make_schedule(calendar)
    state = resolve_state(
        tasks[1], ProgressEntry("B", percent_complete=50.0), date(2026, 9, 8), calendar
    )
    assert state["remaining_duration"] == 2  # half of 4


def test_no_entry_means_not_started(calendar):
    tasks, _ = make_schedule(calendar)
    state = resolve_state(tasks[2], None, date(2026, 9, 1), calendar)
    assert state["status"] == STATUS_NOT_STARTED
    assert state["remaining_duration"] == 2


def test_out_of_range_values_are_clamped(calendar):
    tasks, _ = make_schedule(calendar)
    state = resolve_state(
        tasks[0], ProgressEntry("A", percent_complete=180.0), date(2026, 9, 8), calendar
    )
    assert state["percent_complete"] == 100.0
    state = resolve_state(
        tasks[0], ProgressEntry("A", percent_complete=-20.0), date(2026, 9, 1), calendar
    )
    assert state["status"] == STATUS_NOT_STARTED


def test_finish_before_start_is_clamped(calendar):
    tasks, _ = make_schedule(calendar)
    state = resolve_state(
        tasks[0],
        ProgressEntry("A", actual_start=date(2026, 9, 4), actual_finish=date(2026, 9, 2)),
        date(2026, 9, 8),
        calendar,
    )
    assert state["actual_finish"] == state["actual_start"]
    assert any("clamped" in note for note in state["progress_assumptions"])


# --- planned percent --------------------------------------------------------


def test_planned_percent_at(calendar):
    start, finish = date(2026, 9, 1), date(2026, 9, 4)  # 4 working days
    assert planned_percent_at(start, finish, date(2026, 8, 31), calendar) == 0.0
    assert planned_percent_at(start, finish, date(2026, 9, 1), calendar) == 0.0
    assert planned_percent_at(start, finish, date(2026, 9, 3), calendar) == 50.0
    assert planned_percent_at(start, finish, date(2026, 9, 7), calendar) == 100.0


# --- forecast and variance ----------------------------------------------------


def test_on_plan_progress_forecasts_the_baseline_finish(calendar):
    tasks, links = make_schedule(calendar)
    baseline = snapshot_baseline(tasks)
    # Data date 4 Sep: A finished exactly as planned, B has not been due yet.
    result = evaluate_progress(
        tasks, links, calendar, "2026-09-04",
        [{"task_id": "A", "percent_complete": 100, "actual_start": "2026-09-01",
          "actual_finish": "2026-09-03"}],
        baseline,
    )
    rows = by_id(result)
    assert rows["A"]["schedule_flag"] == FLAG_COMPLETE
    assert rows["B"]["finish_variance_days"] == 0
    assert rows["C"]["forecast_finish"] == "2026-09-11"
    assert result.summary["finish_variance_days"] == 0
    assert result.summary["variance_basis"] == "baseline"


def test_late_finish_pushes_successors_and_the_project(calendar):
    tasks, links = make_schedule(calendar)
    baseline = snapshot_baseline(tasks)
    # A took two extra working days.
    result = evaluate_progress(
        tasks, links, calendar, "2026-09-08",
        [{"task_id": "A", "actual_start": "2026-09-01", "actual_finish": "2026-09-07"}],
        baseline,
    )
    rows = by_id(result)
    assert rows["A"]["finish_variance_days"] == 2
    assert rows["B"]["forecast_start"] == "2026-09-08"
    assert rows["B"]["schedule_flag"] == FLAG_BEHIND
    assert rows["C"]["forecast_finish"] == "2026-09-15"
    assert result.summary["forecast_finish"] == "2026-09-15"
    assert result.summary["finish_variance_days"] == 2


def test_early_finish_pulls_the_forecast_in(calendar):
    tasks, links = make_schedule(calendar)
    baseline = snapshot_baseline(tasks)
    result = evaluate_progress(
        tasks, links, calendar, "2026-09-03",
        [{"task_id": "A", "actual_start": "2026-09-01", "actual_finish": "2026-09-02"}],
        baseline,
    )
    rows = by_id(result)
    assert rows["B"]["forecast_start"] == "2026-09-03"
    assert rows["B"]["schedule_flag"] == FLAG_AHEAD
    assert result.summary["finish_variance_days"] == -1


def test_not_started_work_cannot_start_before_the_data_date(calendar):
    tasks, links = make_schedule(calendar)
    result = evaluate_progress(tasks, links, calendar, "2026-09-10", [], snapshot_baseline(tasks))
    rows = by_id(result)
    # Nothing has happened; A should have finished long ago.
    assert rows["A"]["forecast_start"] == "2026-09-10"
    assert rows["A"]["delay_cause"] == "late_start"
    # C is only late because the chain in front of it slipped.
    assert rows["C"]["delay_cause"] == "predecessor_delay"


def test_slow_progress_is_diagnosed(calendar):
    tasks, links = make_schedule(calendar)
    result = evaluate_progress(
        tasks, links, calendar, "2026-09-03",
        [{"task_id": "A", "percent_complete": 10, "actual_start": "2026-09-01"}],
        snapshot_baseline(tasks),
    )
    row = by_id(result)["A"]
    assert row["schedule_flag"] == FLAG_BEHIND
    assert row["delay_cause"] == "slow_progress"
    assert row["percent_variance"] < 0


def test_future_work_that_is_not_due_is_not_started_not_behind(calendar):
    tasks, links = make_schedule(calendar)
    result = evaluate_progress(tasks, links, calendar, "2026-09-01", [], snapshot_baseline(tasks))
    rows = by_id(result)
    assert rows["C"]["schedule_flag"] == FLAG_NOT_STARTED
    assert rows["A"]["schedule_flag"] in (FLAG_NOT_STARTED, FLAG_ON_TRACK)
    assert result.summary["finish_variance_days"] == 0


def test_without_a_baseline_variance_is_measured_against_the_plan(calendar):
    tasks, links = make_schedule(calendar)
    result = evaluate_progress(tasks, links, calendar, "2026-09-01", [])
    assert result.summary["variance_basis"] == "plan"
    assert not by_id(result)["A"]["in_baseline"]


def test_summary_rollups(calendar):
    tasks, links = make_schedule(calendar)
    result = evaluate_progress(
        tasks, links, calendar, "2026-09-08",
        [
            {"task_id": "A", "actual_start": "2026-09-01", "actual_finish": "2026-09-03"},
            {"task_id": "B", "quantity_placed": 100.0, "actual_start": "2026-09-04"},
        ],
        snapshot_baseline(tasks),
    )
    summary = result.summary
    assert summary["by_status"] == {"complete": 1, "in_progress": 1, "not_started": 1}
    assert summary["quantity_by_unit"]["m3"] == {"placed": 30.0, "total": 30.0, "percent": 100.0}
    assert summary["quantity_by_unit"]["m2"]["placed"] == 100.0
    assert 0 < summary["actual_percent_complete"] < summary["planned_percent_complete"]
    assert summary["schedule_performance_index"] < 1.0


def test_critical_behind_lists_only_critical_late_work(calendar):
    tasks, links = make_schedule(calendar)
    result = evaluate_progress(tasks, links, calendar, "2026-09-10", [], snapshot_baseline(tasks))
    at_risk = result.summary["critical_behind"]
    assert at_risk
    assert all(item["finish_variance_days"] > 0 for item in at_risk)


def test_orphaned_progress_is_ignored_with_a_warning(calendar):
    tasks, links = make_schedule(calendar)
    result = evaluate_progress(
        tasks, links, calendar, "2026-09-02", [{"task_id": "GONE", "percent_complete": 50}]
    )
    assert result.warnings
    assert "GONE" not in by_id(result)


def test_bad_data_date_is_rejected(calendar):
    tasks, links = make_schedule(calendar)
    with pytest.raises(ValueError, match="data date"):
        evaluate_progress(tasks, links, calendar, "someday", [])


def test_the_plan_itself_is_never_mutated(calendar):
    tasks, links = make_schedule(calendar)
    before = [dict(task) for task in tasks]
    evaluate_progress(
        tasks, links, calendar, "2026-09-08",
        [{"task_id": "A", "actual_start": "2026-09-01", "actual_finish": "2026-09-07"}],
    )
    assert tasks == before


# --- against the real sample model -------------------------------------------


def test_progress_on_the_sample_model(elements):
    from app.schedule.pipeline import ScheduleOptions, generate_schedule

    schedule = generate_schedule(elements, ScheduleOptions(level="L3", start_date=START))
    calendar = WorkCalendar(start_date=START)
    first = min(schedule.tasks, key=lambda t: (t["early_start_offset"], t["id"]))
    result = evaluate_progress(
        schedule.tasks,
        schedule.links,
        calendar,
        "2026-09-15",
        [{"task_id": first["id"], "percent_complete": 100}],
        snapshot_baseline(schedule.tasks),
    )
    assert len(result.tasks) == len(schedule.tasks)
    assert result.summary["by_status"]["complete"] == 1
    assert result.summary["forecast_finish"] >= result.summary["reference_finish"]
    for row in result.tasks:
        assert row["forecast_start"] <= row["forecast_finish"]
