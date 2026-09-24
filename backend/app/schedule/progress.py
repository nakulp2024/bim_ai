"""Progress, baseline variance and forecasting.

The plan says what should happen; progress says what did. This module turns
the two into the answers a site team actually asks:

  * Where does each activity stand as of the data date?
  * Is it ahead of or behind the baseline, and by how many working days?
  * Given what has really happened, when will the job finish?

Progress entries are the source of truth. Everything here is derived on read
and never written back over the plan, so the as-planned schedule, the baseline
and the forecast can always be compared side by side.

Conventions follow P6: the data date is the first day of *remaining* work.
Progress reported "as of" the data date covers work done before it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..util import as_float
from .calendar import WorkCalendar
from .cpm import CpmTask, calculate

STATUS_NOT_STARTED = "not_started"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETE = "complete"

FLAG_COMPLETE = "complete"
FLAG_AHEAD = "ahead"
FLAG_ON_TRACK = "on_track"
FLAG_BEHIND = "behind"
FLAG_NOT_STARTED = "not_started"

# A reported percent and a quantity-derived percent this far apart are worth a
# second look by whoever reported them.
PERCENT_DISAGREEMENT_PP = 15.0


@dataclass
class ProgressEntry:
    """The latest reported state of one task."""

    task_id: str
    percent_complete: float | None = None
    quantity_placed: float | None = None
    actual_start: date | None = None
    actual_finish: date | None = None
    reported_on: date | None = None
    note: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProgressEntry:
        return cls(
            task_id=str(data.get("task_id")),
            percent_complete=as_float(data.get("percent_complete")),
            quantity_placed=as_float(data.get("quantity_placed")),
            actual_start=_to_date(data.get("actual_start")),
            actual_finish=_to_date(data.get("actual_finish")),
            reported_on=_to_date(data.get("reported_on")),
            note=data.get("note") or None,
        )


@dataclass
class ProgressResult:
    tasks: list[dict[str, Any]]
    summary: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"tasks": self.tasks, "summary": self.summary, "warnings": self.warnings}


def _to_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


# --------------------------------------------------------------------------
# per-task state
# --------------------------------------------------------------------------


def resolve_state(
    task: dict[str, Any],
    entry: ProgressEntry | None,
    data_date: date,
    calendar: WorkCalendar,
) -> dict[str, Any]:
    """Turn one raw progress entry into a complete, consistent task state.

    Field data is always incomplete, so every gap is filled by a stated rule
    and the rule is recorded in ``assumptions`` rather than applied silently.
    """
    assumptions: list[str] = []
    duration = max(0, int(task.get("duration_days") or 0))
    total_quantity = as_float(task.get("quantity"))
    planned_start = _to_date(task.get("start_date"))

    percent: float | None = None
    placed: float | None = None
    if entry is not None:
        percent = entry.percent_complete
        placed = entry.quantity_placed

    # --- reconcile percent and quantity ------------------------------------
    if percent is not None:
        percent = max(0.0, min(100.0, percent))
    if placed is not None:
        placed = max(0.0, placed)

    if percent is None and placed is not None and total_quantity:
        percent = min(100.0, 100.0 * placed / total_quantity)
        assumptions.append("percent complete derived from quantity placed")
    elif placed is None and percent is not None and total_quantity:
        placed = total_quantity * percent / 100.0
        assumptions.append("quantity placed derived from percent complete")
    elif percent is not None and placed is not None and total_quantity:
        # Both were reported. Trust the percent the reporter asserted (it can
        # account for work a quantity misses, like formwork before a pour) but
        # flag a large disagreement.
        from_quantity = 100.0 * placed / total_quantity
        if abs(from_quantity - percent) > PERCENT_DISAGREEMENT_PP:
            assumptions.append(
                f"reported {percent:.0f}% disagrees with quantity placed "
                f"({from_quantity:.0f}% of {total_quantity:g})"
            )

    actual_start = entry.actual_start if entry else None
    actual_finish = entry.actual_finish if entry else None

    # --- status --------------------------------------------------------------
    if actual_finish is not None or (percent is not None and percent >= 100.0):
        status = STATUS_COMPLETE
    elif actual_start is not None or (percent is not None and percent > 0.0):
        status = STATUS_IN_PROGRESS
    else:
        status = STATUS_NOT_STARTED

    if status == STATUS_COMPLETE:
        percent = 100.0
        if total_quantity and placed is None:
            placed = total_quantity
        if actual_finish is None:
            # The day before the data date is the last day progress covers.
            actual_finish = calendar.date_for_offset(
                max(0, calendar.offset_for_date(data_date) - 1)
            )
            assumptions.append("actual finish assumed as the last working day before data date")
        if actual_start is None:
            actual_start = min(planned_start or actual_finish, actual_finish)
            assumptions.append("actual start assumed as planned start")
    elif status == STATUS_IN_PROGRESS:
        if actual_start is None:
            actual_start = min(planned_start or data_date, data_date)
            assumptions.append("actual start assumed as planned start")
        if percent is None:
            percent = 0.0
    else:
        percent = 0.0
        placed = placed or 0.0

    if actual_start and actual_finish and actual_finish < actual_start:
        actual_finish = actual_start
        assumptions.append("actual finish was before actual start; clamped")

    # --- remaining work ------------------------------------------------------
    if status == STATUS_COMPLETE:
        remaining = 0
    elif status == STATUS_IN_PROGRESS:
        # Still going, so at least a day is left however high the percent.
        remaining = max(1, math.ceil(duration * (1.0 - (percent or 0.0) / 100.0)))
    else:
        remaining = duration

    return {
        "status": status,
        "percent_complete": round(percent or 0.0, 2),
        "quantity_placed": round(placed, 4) if placed is not None else None,
        "actual_start": _iso(actual_start),
        "actual_finish": _iso(actual_finish),
        "remaining_duration": remaining,
        "progress_note": entry.note if entry else None,
        "progress_reported_on": _iso(entry.reported_on) if entry else None,
        "progress_assumptions": assumptions,
    }


def planned_percent_at(
    start: date | None, finish: date | None, data_date: date, calendar: WorkCalendar
) -> float:
    """How far through its planned window a task should be on the data date."""
    if start is None or finish is None:
        return 0.0
    if data_date <= start:
        return 0.0
    if data_date > finish:
        return 100.0
    total = calendar.working_days_between(start, finish) + 1  # inclusive finish
    elapsed = calendar.working_days_between(start, data_date)
    return round(100.0 * elapsed / max(total, 1), 2)


# --------------------------------------------------------------------------
# forecast
# --------------------------------------------------------------------------


def forecast(
    tasks: list[dict[str, Any]],
    links: list[dict[str, Any]],
    states: dict[str, dict[str, Any]],
    data_date: date,
    calendar: WorkCalendar,
) -> dict[str, Any]:
    """CPM again, but honouring what actually happened.

    * complete     - pinned at its actual dates, zero float, never critical
    * in progress  - pinned at its actual start; finishes after the remaining
                     duration counted from the data date
    * not started  - cannot start before the data date, whatever the logic says
    """
    data_offset = calendar.offset_for_date(data_date)

    predecessors: dict[str, list[dict[str, Any]]] = {task["id"]: [] for task in tasks}
    for link in links:
        successor = link.get("successor_id")
        if successor in predecessors:
            predecessors[successor].append(
                {
                    "id": link.get("predecessor_id"),
                    "type": link.get("type", "FS"),
                    "lag": int(link.get("lag") or 0),
                }
            )

    cpm_tasks: list[CpmTask] = []
    for task in tasks:
        state = states[task["id"]]
        cpm_task = CpmTask(id=task["id"], duration=0, predecessors=predecessors[task["id"]])
        status = state["status"]

        if status == STATUS_COMPLETE:
            start = calendar.offset_for_date(state["actual_start"])
            finish = calendar.offset_for_date(state["actual_finish"])
            cpm_task.pinned_start = start
            cpm_task.duration = max(1, finish - start + 1)
            cpm_task.complete = True
        elif status == STATUS_IN_PROGRESS:
            start = calendar.offset_for_date(state["actual_start"])
            elapsed = max(0, data_offset - start)
            cpm_task.pinned_start = start
            cpm_task.duration = elapsed + state["remaining_duration"]
        else:
            cpm_task.constraint_offset = data_offset
            cpm_task.duration = state["remaining_duration"]
        cpm_tasks.append(cpm_task)

    result = calculate(cpm_tasks)

    forecasts: dict[str, dict[str, Any]] = {}
    for task in tasks:
        computed = result.tasks[task["id"]]
        state = states[task["id"]]
        if state["status"] == STATUS_COMPLETE:
            start_iso, finish_iso = state["actual_start"], state["actual_finish"]
        else:
            start_iso = (
                state["actual_start"]
                if state["status"] == STATUS_IN_PROGRESS
                else calendar.date_for_offset(computed.early_start).isoformat()
            )
            span = max(1, computed.early_finish - computed.early_start)
            finish_iso = calendar.finish_date(computed.early_start, span).isoformat()
        forecasts[task["id"]] = {
            "forecast_start": start_iso,
            "forecast_finish": finish_iso,
            "forecast_total_float": computed.total_float,
            "forecast_critical": bool(computed.is_critical),
        }

    finish_offset = max((t.early_finish for t in result.tasks.values()), default=0)
    return {
        "tasks": forecasts,
        "finish_date": calendar.date_for_offset(max(0, finish_offset - 1)).isoformat()
        if tasks
        else None,
        "critical_path": result.critical_path,
        "cycles_broken": result.cycles_broken,
    }


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def evaluate_progress(
    tasks: list[dict[str, Any]],
    links: list[dict[str, Any]],
    calendar: WorkCalendar,
    data_date: date | str,
    progress: list[dict[str, Any]] | dict[str, dict[str, Any]] | None = None,
    baseline: list[dict[str, Any]] | None = None,
) -> ProgressResult:
    """Overlay progress on a schedule and compare it with a baseline.

    ``progress`` is either a list of entries or a mapping keyed by task id. When
    several entries exist for one task the caller should pass only the latest.
    ``baseline`` is a list of task snapshots; without one, variance is measured
    against the current plan and the summary says so.
    """
    as_of = _to_date(data_date)
    if as_of is None:
        raise ValueError(f"data date is not a date: {data_date!r}")

    entries: dict[str, ProgressEntry] = {}
    raw = progress.values() if isinstance(progress, dict) else (progress or [])
    for item in raw:
        entry = item if isinstance(item, ProgressEntry) else ProgressEntry.from_dict(item)
        entries[entry.task_id] = entry

    warnings: list[str] = []
    task_ids = {task["id"] for task in tasks}
    orphaned = sorted(set(entries) - task_ids)
    if orphaned:
        warnings.append(
            f"{len(orphaned)} progress entr{'y' if len(orphaned) == 1 else 'ies'} "
            "refer to tasks no longer in the schedule and were ignored"
        )

    baseline_by_id = {row["id"]: row for row in (baseline or []) if row.get("id")}
    basis = "baseline" if baseline_by_id else "plan"

    states = {
        task["id"]: resolve_state(task, entries.get(task["id"]), as_of, calendar)
        for task in tasks
    }
    projection = forecast(tasks, links, states, as_of, calendar)
    warnings.extend(
        f"logic cycle broken during forecast: {c['from']} -> {c['to']}"
        for c in projection["cycles_broken"]
    )

    rows: list[dict[str, Any]] = []
    for task in tasks:
        state = states[task["id"]]
        predicted = projection["tasks"][task["id"]]
        reference = baseline_by_id.get(task["id"]) or task
        ref_start = _to_date(reference.get("start_date"))
        ref_finish = _to_date(reference.get("finish_date"))
        ref_duration = int(reference.get("duration_days") or task.get("duration_days") or 0)

        planned_pct = planned_percent_at(ref_start, ref_finish, as_of, calendar)
        forecast_start = _to_date(predicted["forecast_start"])
        forecast_finish = _to_date(predicted["forecast_finish"])

        start_var = (
            calendar.working_days_between(ref_start, forecast_start)
            if ref_start and forecast_start
            else None
        )
        finish_var = (
            calendar.working_days_between(ref_finish, forecast_finish)
            if ref_finish and forecast_finish
            else None
        )

        # A forecast variance in either direction outranks "not due yet": work
        # that has not started but is now forecast to finish early is news.
        if state["status"] == STATUS_COMPLETE:
            flag = FLAG_COMPLETE
        elif finish_var is not None and finish_var > 0:
            flag = FLAG_BEHIND
        elif finish_var is not None and finish_var < 0:
            flag = FLAG_AHEAD
        elif state["status"] == STATUS_NOT_STARTED and planned_pct <= 0:
            flag = FLAG_NOT_STARTED
        else:
            flag = FLAG_ON_TRACK

        # "Behind" alone does not tell a planner what to do about it. A task
        # that should have started and has not is a different problem from
        # one that is merely being pushed by a slipping predecessor.
        delay_cause = None
        if flag == FLAG_BEHIND:
            if state["status"] == STATUS_IN_PROGRESS:
                delay_cause = (
                    "slow_progress"
                    if state["percent_complete"] < planned_pct
                    else "late_start"
                )
            elif planned_pct > 0:
                delay_cause = "late_start"
            else:
                delay_cause = "predecessor_delay"

        rows.append(
            {
                **task,
                **state,
                **predicted,
                "baseline_start": _iso(ref_start),
                "baseline_finish": _iso(ref_finish),
                "baseline_duration": ref_duration,
                "in_baseline": task["id"] in baseline_by_id,
                "planned_percent": planned_pct,
                "percent_variance": round(state["percent_complete"] - planned_pct, 2),
                "start_variance_days": start_var,
                "finish_variance_days": finish_var,
                "schedule_flag": flag,
                "delay_cause": delay_cause,
            }
        )

    summary = _summarise(rows, projection, as_of, basis, baseline_by_id, calendar)
    return ProgressResult(tasks=rows, summary=summary, warnings=warnings)


def _summarise(
    rows: list[dict[str, Any]],
    projection: dict[str, Any],
    as_of: date,
    basis: str,
    baseline_by_id: dict[str, dict[str, Any]],
    calendar: WorkCalendar,
) -> dict[str, Any]:
    # Duration-weighted, so a one-day task finishing does not count the same
    # as a forty-day one. Units differ between tasks, so quantity cannot be the
    # weight across the whole project.
    total_weight = sum(max(1, row["baseline_duration"]) for row in rows) or 1
    planned = sum(max(1, r["baseline_duration"]) * r["planned_percent"] for r in rows)
    actual = sum(max(1, r["baseline_duration"]) * r["percent_complete"] for r in rows)
    planned_pct = planned / total_weight
    actual_pct = actual / total_weight

    reference_finishes = [r["baseline_finish"] for r in rows if r["baseline_finish"]]
    reference_finish = max(reference_finishes) if reference_finishes else None
    forecast_finish = projection["finish_date"]
    finish_variance = (
        calendar.working_days_between(reference_finish, forecast_finish)
        if reference_finish and forecast_finish
        else None
    )

    flags: dict[str, int] = {}
    statuses: dict[str, int] = {}
    causes: dict[str, int] = {}
    for row in rows:
        flags[row["schedule_flag"]] = flags.get(row["schedule_flag"], 0) + 1
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
        if row["delay_cause"]:
            causes[row["delay_cause"]] = causes.get(row["delay_cause"], 0) + 1

    quantities: dict[str, dict[str, float]] = {}
    for row in rows:
        unit = row.get("unit")
        total = as_float(row.get("quantity"))
        if not unit or not total:
            continue
        bucket = quantities.setdefault(unit, {"placed": 0.0, "total": 0.0})
        bucket["total"] += total
        bucket["placed"] += as_float(row.get("quantity_placed")) or 0.0

    at_risk = sorted(
        (
            r
            for r in rows
            if r["schedule_flag"] == FLAG_BEHIND and r.get("forecast_critical")
        ),
        key=lambda r: -(r["finish_variance_days"] or 0),
    )

    return {
        "data_date": as_of.isoformat(),
        "variance_basis": basis,
        "baseline_task_count": len(baseline_by_id),
        "task_count": len(rows),
        "planned_percent_complete": round(planned_pct, 2),
        "actual_percent_complete": round(actual_pct, 2),
        # Earned-value style schedule performance, duration-weighted. Below 1.0
        # means less work is done than the plan called for by now.
        "schedule_performance_index": round(actual_pct / planned_pct, 3) if planned_pct else None,
        "reference_finish": reference_finish,
        "forecast_finish": forecast_finish,
        "finish_variance_days": finish_variance,
        "by_status": statuses,
        "by_flag": flags,
        "by_delay_cause": causes,
        "quantity_by_unit": {
            unit: {
                "placed": round(values["placed"], 3),
                "total": round(values["total"], 3),
                "percent": round(100.0 * values["placed"] / values["total"], 2)
                if values["total"]
                else 0.0,
            }
            for unit, values in sorted(quantities.items())
        },
        "critical_behind": [
            {
                "id": r["id"],
                "label": r["label"],
                "finish_variance_days": r["finish_variance_days"],
                "forecast_finish": r["forecast_finish"],
                "delay_cause": r["delay_cause"],
            }
            for r in at_risk[:20]
        ],
        "forecast_critical_path": projection["critical_path"],
    }


def snapshot_baseline(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The fields a baseline needs, and nothing that would bloat it."""
    keep = (
        "id",
        "label",
        "wbs_code",
        "duration_days",
        "start_date",
        "finish_date",
        "early_start_offset",
        "early_finish_offset",
        "quantity",
        "unit",
        "is_critical",
        "total_float",
    )
    return [{key: task.get(key) for key in keep} for task in tasks]
