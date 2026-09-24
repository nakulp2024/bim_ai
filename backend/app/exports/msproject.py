"""MS Project XML (MSPDI) export."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from xml.etree import ElementTree as ET

MSPDI_NS = "http://schemas.microsoft.com/project"

LINK_TYPE_CODES = {"FF": 0, "FS": 1, "SF": 2, "SS": 3}


def _text(parent: ET.Element, tag: str, value: Any) -> None:
    node = ET.SubElement(parent, tag)
    node.text = "" if value is None else str(value)


def _stamp(value: str | None, hour: int) -> str:
    try:
        parsed = date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        parsed = date.today()
    return datetime(parsed.year, parsed.month, parsed.day, hour, 0, 0).isoformat()


def to_msproject_xml(schedule: dict[str, Any], project_name: str = "Schedule") -> bytes:
    tasks = schedule.get("tasks") or []
    calendar = schedule.get("calendar") or {}
    work_days = set(calendar.get("work_days") or [0, 1, 2, 3, 4])
    start = calendar.get("start_date") or date.today().isoformat()

    ET.register_namespace("", MSPDI_NS)
    root = ET.Element(f"{{{MSPDI_NS}}}Project")
    _text(root, f"{{{MSPDI_NS}}}Name", project_name)
    _text(root, f"{{{MSPDI_NS}}}Title", project_name)
    _text(root, f"{{{MSPDI_NS}}}ScheduleFromStart", "1")
    _text(root, f"{{{MSPDI_NS}}}StartDate", _stamp(start, 8))
    _text(root, f"{{{MSPDI_NS}}}CalendarUID", "1")
    _text(root, f"{{{MSPDI_NS}}}DurationFormat", "7")  # days
    _text(root, f"{{{MSPDI_NS}}}MinutesPerDay", "480")
    _text(root, f"{{{MSPDI_NS}}}MinutesPerWeek", str(480 * max(1, len(work_days))))
    _text(root, f"{{{MSPDI_NS}}}DaysPerMonth", "20")

    # --- calendar ---------------------------------------------------------
    calendars = ET.SubElement(root, f"{{{MSPDI_NS}}}Calendars")
    calendar_node = ET.SubElement(calendars, f"{{{MSPDI_NS}}}Calendar")
    _text(calendar_node, f"{{{MSPDI_NS}}}UID", "1")
    _text(calendar_node, f"{{{MSPDI_NS}}}Name", "Project Calendar")
    _text(calendar_node, f"{{{MSPDI_NS}}}IsBaseCalendar", "1")
    _text(calendar_node, f"{{{MSPDI_NS}}}BaseCalendarUID", "-1")
    week_days = ET.SubElement(calendar_node, f"{{{MSPDI_NS}}}WeekDays")
    # MSPDI DayType: 1=Sunday .. 7=Saturday; python weekday(): 0=Monday.
    for python_day in range(7):
        mspdi_day = (python_day + 1) % 7 + 1
        day = ET.SubElement(week_days, f"{{{MSPDI_NS}}}WeekDay")
        _text(day, f"{{{MSPDI_NS}}}DayType", str(mspdi_day))
        working = python_day in work_days
        _text(day, f"{{{MSPDI_NS}}}DayWorking", "1" if working else "0")
        if working:
            times = ET.SubElement(day, f"{{{MSPDI_NS}}}WorkingTimes")
            period = ET.SubElement(times, f"{{{MSPDI_NS}}}WorkingTime")
            _text(period, f"{{{MSPDI_NS}}}FromTime", "08:00:00")
            _text(period, f"{{{MSPDI_NS}}}ToTime", "16:00:00")

    exceptions = ET.SubElement(calendar_node, f"{{{MSPDI_NS}}}Exceptions")
    for index, holiday in enumerate(calendar.get("holidays") or [], start=1):
        exception = ET.SubElement(exceptions, f"{{{MSPDI_NS}}}Exception")
        _text(exception, f"{{{MSPDI_NS}}}EnteredByOccurrences", "0")
        time_period = ET.SubElement(exception, f"{{{MSPDI_NS}}}TimePeriod")
        _text(time_period, f"{{{MSPDI_NS}}}FromDate", _stamp(holiday, 0))
        _text(time_period, f"{{{MSPDI_NS}}}ToDate", _stamp(holiday, 23))
        _text(exception, f"{{{MSPDI_NS}}}Occurrences", "1")
        _text(exception, f"{{{MSPDI_NS}}}Name", f"Holiday {index}")
        _text(exception, f"{{{MSPDI_NS}}}Type", "1")
        _text(exception, f"{{{MSPDI_NS}}}DayWorking", "0")

    # --- tasks ------------------------------------------------------------
    uid_by_id = {task["id"]: index + 1 for index, task in enumerate(tasks)}
    progress = (schedule.get("progress") or {}).get("tasks") or {}
    tasks_node = ET.SubElement(root, f"{{{MSPDI_NS}}}Tasks")
    for index, task in enumerate(tasks):
        uid = uid_by_id[task["id"]]
        state = progress.get(task["id"])
        node = ET.SubElement(tasks_node, f"{{{MSPDI_NS}}}Task")
        _text(node, f"{{{MSPDI_NS}}}UID", uid)
        _text(node, f"{{{MSPDI_NS}}}ID", index + 1)
        _text(node, f"{{{MSPDI_NS}}}Name", task.get("label"))
        _text(node, f"{{{MSPDI_NS}}}Type", "1")  # fixed duration
        _text(node, f"{{{MSPDI_NS}}}OutlineNumber", task.get("wbs_code") or str(index + 1))
        _text(node, f"{{{MSPDI_NS}}}OutlineLevel", "1")
        _text(node, f"{{{MSPDI_NS}}}WBS", task.get("wbs_code") or str(index + 1))
        _text(node, f"{{{MSPDI_NS}}}Active", "1")
        _text(node, f"{{{MSPDI_NS}}}Manual", "0")
        _text(node, f"{{{MSPDI_NS}}}Summary", "0")
        is_milestone = int(task.get("duration_days") or 1) == 0
        _text(node, f"{{{MSPDI_NS}}}Milestone", "1" if is_milestone else "0")
        _text(node, f"{{{MSPDI_NS}}}Critical", "1" if task.get("is_critical") else "0")
        duration_days = max(0, int(task.get("duration_days") or 0))
        _text(node, f"{{{MSPDI_NS}}}Duration", f"PT{duration_days * 8}H0M0S")
        _text(node, f"{{{MSPDI_NS}}}DurationFormat", "7")
        _text(node, f"{{{MSPDI_NS}}}Start", _stamp(task.get("start_date"), 8))
        _text(node, f"{{{MSPDI_NS}}}Finish", _stamp(task.get("finish_date"), 16))
        _text(node, f"{{{MSPDI_NS}}}EarlyStart", _stamp(task.get("start_date"), 8))
        _text(node, f"{{{MSPDI_NS}}}EarlyFinish", _stamp(task.get("finish_date"), 16))
        _text(node, f"{{{MSPDI_NS}}}LateStart", _stamp(task.get("late_start_date"), 8))
        _text(node, f"{{{MSPDI_NS}}}LateFinish", _stamp(task.get("late_finish_date"), 16))
        _text(node, f"{{{MSPDI_NS}}}TotalSlack", int(task.get("total_float") or 0) * 4800)
        _text(node, f"{{{MSPDI_NS}}}FreeSlack", int(task.get("free_float") or 0) * 4800)
        if state:
            # Updates out: Project reads these as the task's reported progress.
            if state.get("actual_start"):
                _text(node, f"{{{MSPDI_NS}}}ActualStart", _stamp(state["actual_start"], 8))
            if state.get("actual_finish"):
                _text(node, f"{{{MSPDI_NS}}}ActualFinish", _stamp(state["actual_finish"], 16))
            _text(
                node,
                f"{{{MSPDI_NS}}}PercentComplete",
                int(round(float(state.get("percent_complete") or 0))),
            )
            remaining = max(0, int(state.get("remaining_duration") or 0))
            _text(node, f"{{{MSPDI_NS}}}RemainingDuration", f"PT{remaining * 8}H0M0S")
        _text(node, f"{{{MSPDI_NS}}}CalendarUID", "1")
        # Source traceability travels in the notes field so it survives a
        # round trip through Project.
        _text(
            node,
            f"{{{MSPDI_NS}}}Notes",
            "GlobalIds: " + ";".join(task.get("element_ids") or []),
        )
        for link in task.get("predecessors") or []:
            predecessor_uid = uid_by_id.get(link.get("id"))
            if predecessor_uid is None:
                continue
            link_node = ET.SubElement(node, f"{{{MSPDI_NS}}}PredecessorLink")
            _text(link_node, f"{{{MSPDI_NS}}}PredecessorUID", predecessor_uid)
            _text(
                link_node,
                f"{{{MSPDI_NS}}}Type",
                LINK_TYPE_CODES.get(str(link.get("type") or "FS").upper(), 1),
            )
            _text(link_node, f"{{{MSPDI_NS}}}LinkLag", int(link.get("lag") or 0) * 4800)
            _text(link_node, f"{{{MSPDI_NS}}}LagFormat", "7")

        if state and state.get("in_baseline") and state.get("baseline_start"):
            baseline = ET.SubElement(node, f"{{{MSPDI_NS}}}Baseline")
            _text(baseline, f"{{{MSPDI_NS}}}Number", "0")
            _text(baseline, f"{{{MSPDI_NS}}}Start", _stamp(state["baseline_start"], 8))
            _text(baseline, f"{{{MSPDI_NS}}}Finish", _stamp(state["baseline_finish"], 16))
            baseline_days = max(0, int(state.get("baseline_duration") or 0))
            _text(baseline, f"{{{MSPDI_NS}}}Duration", f"PT{baseline_days * 8}H0M0S")
            _text(baseline, f"{{{MSPDI_NS}}}DurationFormat", "7")

    tree_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return tree_bytes


def working_days_between(start: date, end: date, work_days: set[int]) -> int:
    count = 0
    cursor = start
    while cursor <= end:
        if cursor.weekday() in work_days:
            count += 1
        cursor += timedelta(days=1)
    return count
