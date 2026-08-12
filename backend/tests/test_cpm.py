"""CPM: forward pass, backward pass, float, critical path, calendar."""

from __future__ import annotations

from datetime import date

import pytest

from app.schedule.calendar import WorkCalendar
from app.schedule.cpm import CpmTask, calculate


def task(task_id: str, duration: int, *predecessors) -> CpmTask:
    links = [
        {"id": p[0], "type": p[1], "lag": p[2]}
        if isinstance(p, tuple)
        else {"id": p, "type": "FS", "lag": 0}
        for p in predecessors
    ]
    return CpmTask(id=task_id, duration=duration, predecessors=links)


# --- forward pass ---------------------------------------------------------


def test_simple_chain():
    result = calculate([task("A", 3), task("B", 2, "A"), task("C", 4, "B")])
    assert (result.tasks["A"].early_start, result.tasks["A"].early_finish) == (0, 3)
    assert (result.tasks["B"].early_start, result.tasks["B"].early_finish) == (3, 5)
    assert (result.tasks["C"].early_start, result.tasks["C"].early_finish) == (5, 9)
    assert result.project_duration == 9


def test_parallel_branches_take_the_longest_path():
    result = calculate(
        [
            task("Start", 1),
            task("Long", 6, "Start"),
            task("Short", 2, "Start"),
            task("End", 1, "Long", "Short"),
        ]
    )
    assert result.tasks["End"].early_start == 7
    assert result.project_duration == 8
    assert result.tasks["Short"].total_float == 4
    assert result.tasks["Long"].total_float == 0


@pytest.mark.parametrize(
    ("link_type", "lag", "expected_start"),
    [
        ("FS", 0, 5),
        ("FS", 2, 7),
        ("FS", -1, 4),
        ("SS", 0, 0),
        ("SS", 3, 3),
    ],
)
def test_link_types_drive_the_successor_start(link_type, lag, expected_start):
    result = calculate([task("A", 5), task("B", 2, ("A", link_type, lag))])
    assert result.tasks["B"].early_start == expected_start


def test_finish_to_finish_aligns_the_finishes():
    result = calculate([task("A", 5), task("B", 2, ("A", "FF", 1))])
    # B must finish at least 1 day after A finishes: EF(B) >= 6, so ES(B) = 4.
    assert result.tasks["B"].early_finish == 6
    assert result.tasks["B"].early_start == 4


def test_start_to_finish():
    result = calculate([task("A", 5), task("B", 2, ("A", "SF", 4))])
    # EF(B) >= ES(A) + 4 = 4, so ES(B) = 2.
    assert result.tasks["B"].early_finish == 4
    assert result.tasks["B"].early_start == 2


def test_negative_lag_cannot_push_a_task_before_the_project_start():
    result = calculate([task("A", 2), task("B", 2, ("A", "FS", -10))])
    assert result.tasks["B"].early_start == 0


# --- backward pass and float ---------------------------------------------


def test_backward_pass_and_total_float():
    result = calculate(
        [task("A", 2), task("B", 3, "A"), task("C", 1, "A"), task("D", 2, "B", "C")]
    )
    assert result.tasks["C"].total_float == 2
    assert result.tasks["C"].late_start == 4
    assert result.tasks["C"].late_finish == 5
    assert result.tasks["B"].total_float == 0
    assert result.project_duration == 7


def test_free_float_is_bounded_by_the_earliest_successor():
    result = calculate([task("A", 2), task("B", 1, "A"), task("C", 5, "A"), task("D", 1, "B", "C")])
    assert result.tasks["B"].free_float == 4
    assert result.tasks["C"].free_float == 0
    # A leaf task's free float falls back to its total float.
    assert result.tasks["D"].free_float == result.tasks["D"].total_float


def test_critical_path_is_the_zero_float_chain():
    result = calculate(
        [task("A", 2), task("B", 3, "A"), task("C", 1, "A"), task("D", 2, "B", "C")]
    )
    assert result.critical_path == ["A", "B", "D"]
    assert all(result.tasks[t].is_critical for t in ("A", "B", "D"))
    assert not result.tasks["C"].is_critical


def test_every_task_on_a_single_chain_is_critical():
    result = calculate([task("A", 1), task("B", 1, "A"), task("C", 1, "B")])
    assert result.critical_path == ["A", "B", "C"]


# --- robustness -----------------------------------------------------------


def test_cycles_are_broken_and_reported():
    result = calculate([task("A", 2, "C"), task("B", 2, "A"), task("C", 2, "B")])
    assert result.cycles_broken
    assert len(result.order) == 3
    assert result.project_duration > 0


def test_self_links_and_unknown_predecessors_are_dropped():
    result = calculate([task("A", 2, "A", "GHOST"), task("B", 1, "A")])
    reasons = {link["reason"] for link in result.dropped_links}
    assert reasons == {"self_link", "unknown_task"}
    assert result.tasks["A"].predecessors == []
    assert result.project_duration == 3


def test_unknown_link_type_degrades_to_fs():
    result = calculate([task("A", 3), task("B", 1, ("A", "XX", 0))])
    assert result.tasks["B"].predecessors[0]["type"] == "FS"
    assert result.tasks["B"].early_start == 3


def test_zero_duration_milestone():
    result = calculate([task("A", 2), task("M", 0, "A"), task("B", 1, "M")])
    assert result.tasks["M"].early_start == result.tasks["M"].early_finish == 2
    assert result.tasks["B"].early_start == 2


def test_no_tasks():
    result = calculate([])
    assert result.project_duration == 0
    assert result.critical_path == []


def test_disconnected_tasks_all_start_at_zero():
    result = calculate([task("A", 3), task("B", 5), task("C", 1)])
    assert {t.early_start for t in result.tasks.values()} == {0}
    assert result.project_duration == 5
    assert result.tasks["B"].is_critical
    assert not result.tasks["A"].is_critical


def test_result_is_deterministic():
    def build():
        return [task("A", 2), task("B", 3, "A"), task("C", 1, "A"), task("D", 2, "B", "C")]
    first = calculate(build())
    second = calculate(build())
    assert first.order == second.order
    assert first.critical_path == second.critical_path


# --- calendar -------------------------------------------------------------


def test_calendar_skips_weekends():
    calendar = WorkCalendar(start_date=date(2026, 9, 4))  # a Friday
    assert calendar.date_for_offset(0) == date(2026, 9, 4)
    assert calendar.date_for_offset(1) == date(2026, 9, 7)  # Monday
    assert calendar.date_for_offset(5) == date(2026, 9, 11)


def test_calendar_skips_holidays():
    calendar = WorkCalendar(start_date=date(2026, 9, 7), holidays=["2026-09-08"])
    assert calendar.date_for_offset(0) == date(2026, 9, 7)
    assert calendar.date_for_offset(1) == date(2026, 9, 9)


def test_start_date_rolls_forward_to_a_working_day():
    calendar = WorkCalendar(start_date=date(2026, 9, 5))  # a Saturday
    assert calendar.start_date == date(2026, 9, 7)


def test_six_day_week_is_configurable():
    calendar = WorkCalendar(start_date=date(2026, 9, 7), work_days=[0, 1, 2, 3, 4, 5])
    assert calendar.date_for_offset(5) == date(2026, 9, 12)  # Saturday is worked
    assert calendar.date_for_offset(6) == date(2026, 9, 14)  # Sunday is not
    assert calendar.as_dict()["days_per_week"] == 6


def test_finish_date_is_inclusive():
    calendar = WorkCalendar(start_date=date(2026, 9, 7))
    assert calendar.finish_date(0, 1) == date(2026, 9, 7)
    assert calendar.finish_date(0, 5) == date(2026, 9, 11)


def test_bad_dates_and_holidays_are_ignored():
    calendar = WorkCalendar(start_date="not-a-date", holidays=["nope", None, "2026-09-08"])
    assert calendar.start_date == WorkCalendar().start_date
    assert date(2026, 9, 8) in calendar.holidays
