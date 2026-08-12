"""Primavera P6 XER export.

XER is a tab-delimited flat file: %T table, %F field names, %R rows, %E end.
This writer emits the minimum table set P6 needs to import a CPM schedule:
CURRTYPE, PROJECT, CALENDAR, PROJWBS, TASK and TASKPRED.
"""

from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any

XER_VERSION = "19.12"
PROJ_ID = 1
CALENDAR_ID = 1
WBS_ROOT_ID = 1
CURRENCY_ID = 1

LINK_TYPE_CODES = {
    "FS": "PR_FS",
    "SS": "PR_SS",
    "FF": "PR_FF",
    "SF": "PR_SF",
}

WEEKDAY_TO_XER = {6: 1, 0: 2, 1: 3, 2: 4, 3: 5, 4: 6, 5: 7}  # python weekday -> XER day index


class _Writer:
    def __init__(self) -> None:
        self.buffer = io.StringIO()

    def table(self, name: str, fields: list[str], rows: list[list[Any]]) -> None:
        self.buffer.write(f"%T\t{name}\n")
        self.buffer.write("%F\t" + "\t".join(fields) + "\n")
        for row in rows:
            cells = ["" if value is None else str(value).replace("\t", " ").replace("\n", " ")
                     for value in row]
            self.buffer.write("%R\t" + "\t".join(cells) + "\n")

    def value(self) -> str:
        return self.buffer.getvalue()


def _xer_date(value: Any, hour: str = "00:00") -> str:
    try:
        parsed = date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        parsed = date.today()
    return f"{parsed.isoformat()} {hour}"


def _calendar_data(work_days: set[int]) -> str:
    """P6's packed calendar string: seven day blocks, working days get a shift."""
    parts = ["(0||CalendarData()("]
    for python_day, xer_day in sorted(WEEKDAY_TO_XER.items(), key=lambda item: item[1]):
        shift = "(0||0(s|08:00|f|16:00)())" if python_day in work_days else "()"
        parts.append(f"(0||{xer_day}(){shift})")
    parts.append("))")
    return "".join(parts)


def to_p6_xer(schedule: dict[str, Any], project_name: str = "Schedule") -> bytes:
    tasks = schedule.get("tasks") or []
    calendar = schedule.get("calendar") or {}
    work_days = {int(d) for d in (calendar.get("work_days") or [0, 1, 2, 3, 4])}
    start = calendar.get("start_date") or date.today().isoformat()
    finish = (schedule.get("report") or {}).get("cpm", {}).get("finish_date") or start
    short_name = "".join(ch for ch in project_name if ch.isalnum())[:20] or "IFCSCHED"

    writer = _Writer()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    writer.buffer.write(
        f"ERMHDR\t{XER_VERSION}\t{stamp}\tProject\tifc-schedule\tifc-schedule\t"
        f"Project Management\tdbxDatabaseNoName\tProject\tUSD\n"
    )

    writer.table(
        "CURRTYPE",
        ["curr_id", "decimal_digit_cnt", "curr_symbol", "decimal_symbol", "digit_group_symbol",
         "pos_curr_fmt_type", "neg_curr_fmt_type", "curr_type", "curr_short_name",
         "group_digit_cnt",
         "base_exch_rate"],
        [[CURRENCY_ID, 2, "$", ".", ",", "#1.1", "(#1.1)", "US Dollar", "USD", 3, 1.0]],
    )

    writer.table(
        "PROJECT",
        ["proj_id", "proj_short_name", "proj_name", "plan_start_date", "plan_end_date",
         "last_recalc_date", "clndr_id", "sum_data_flag", "task_code_base", "task_code_step",
         "task_code_prefix", "def_duration_type", "fy_start_month_num", "week_start_day_num",
         "day_hr_cnt", "week_hr_cnt", "month_hr_cnt", "year_hr_cnt", "chng_eff_cmp_pct_flag"],
        [[
            PROJ_ID, short_name, project_name, _xer_date(start, "08:00"),
            _xer_date(finish, "16:00"),
            _xer_date(start, "08:00"), CALENDAR_ID, "N", 1000, 10, "A", "DT_FixedDrtn",
            1, 2, 8, 8 * max(1, len(work_days)), 172, 2000, "N",
        ]],
    )

    writer.table(
        "CALENDAR",
        ["clndr_id", "default_flag", "clndr_name", "proj_id", "base_clndr_id", "last_chng_date",
         "clndr_type", "day_hr_cnt", "week_hr_cnt", "month_hr_cnt", "year_hr_cnt", "clndr_data"],
        [[
            CALENDAR_ID, "Y", f"{len(work_days)}-Day Workweek", "", "", _xer_date(start, "08:00"),
            "CA_Base", 8, 8 * max(1, len(work_days)), 172, 2000, _calendar_data(work_days),
        ]],
    )

    # One WBS node per distinct wbs_path prefix keeps P6's outline usable.
    wbs_rows: list[list[Any]] = [[
        WBS_ROOT_ID, PROJ_ID, "", short_name, project_name, 1, "N", "WBS_Node", 1,
    ]]
    wbs_ids: dict[tuple[str, ...], int] = {(): WBS_ROOT_ID}
    next_wbs_id = WBS_ROOT_ID + 1
    for task in tasks:
        path = tuple(task.get("wbs_path") or [])
        for depth in range(1, len(path) + 1):
            prefix = path[:depth]
            if prefix in wbs_ids:
                continue
            wbs_ids[prefix] = next_wbs_id
            wbs_rows.append([
                next_wbs_id, PROJ_ID, wbs_ids[prefix[:-1]], f"W{next_wbs_id}", prefix[-1],
                depth + 1, "N", "WBS_Node", next_wbs_id,
            ])
            next_wbs_id += 1

    writer.table(
        "PROJWBS",
        ["wbs_id", "proj_id", "parent_wbs_id", "wbs_short_name", "wbs_name", "proj_node_flag",
         "status_code", "wbs_type", "seq_num"],
        wbs_rows,
    )

    task_ids = {task["id"]: 1000 + index for index, task in enumerate(tasks)}
    task_rows: list[list[Any]] = []
    for index, task in enumerate(tasks):
        duration_hours = max(0, int(task.get("duration_days") or 0)) * 8
        path = tuple(task.get("wbs_path") or [])
        task_rows.append([
            task_ids[task["id"]], PROJ_ID, wbs_ids.get(path, WBS_ROOT_ID), CALENDAR_ID,
            (task.get("wbs_code") or str(index + 1))[:40], str(task.get("label") or "")[:200],
            "TT_Task", "TK_NotStart", duration_hours, duration_hours, duration_hours,
            _xer_date(task.get("start_date"), "08:00"), _xer_date(task.get("finish_date"), "16:00"),
            _xer_date(task.get("start_date"), "08:00"), _xer_date(task.get("finish_date"), "16:00"),
            _xer_date(task.get("late_start_date"), "08:00"),
            _xer_date(task.get("late_finish_date"), "16:00"),
            int(task.get("total_float") or 0) * 8, int(task.get("free_float") or 0) * 8,
            "N", "DT_FixedDrtn", index + 1,
        ])

    writer.table(
        "TASK",
        ["task_id", "proj_id", "wbs_id", "clndr_id", "task_code", "task_name", "task_type",
         "status_code", "target_drtn_hr_cnt", "remain_drtn_hr_cnt", "total_drtn_hr_cnt",
         "target_start_date", "target_end_date", "early_start_date", "early_end_date",
         "late_start_date", "late_end_date", "total_float_hr_cnt", "free_float_hr_cnt",
         "cstr_type", "duration_type", "seq_num"],
        task_rows,
    )

    pred_rows: list[list[Any]] = []
    pred_id = 1
    for task in tasks:
        for link in task.get("predecessors") or []:
            predecessor = task_ids.get(link.get("id"))
            if predecessor is None:
                continue
            pred_rows.append([
                pred_id, task_ids[task["id"]], predecessor, PROJ_ID, PROJ_ID,
                LINK_TYPE_CODES.get(str(link.get("type") or "FS").upper(), "PR_FS"),
                int(link.get("lag") or 0) * 8,
            ])
            pred_id += 1

    writer.table(
        "TASKPRED",
        ["task_pred_id", "task_id", "pred_task_id", "proj_id", "pred_proj_id", "pred_type",
         "lag_hr_cnt"],
        pred_rows,
    )

    # P6 ignores unknown UDF tables, but the GlobalIds must survive the export,
    # so they ride along in a clearly-named custom table.
    writer.table(
        "IFCSOURCE",
        ["task_id", "task_code", "global_ids"],
        [[task_ids[task["id"]], task.get("wbs_code"), ";".join(task.get("element_ids") or [])]
         for task in tasks],
    )

    writer.buffer.write("%E\n")
    return writer.value().encode("utf-8")
