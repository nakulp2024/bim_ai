"""CSV and XLSX exports."""

from __future__ import annotations

import csv
import io
from typing import Any

COLUMNS = [
    ("wbs_code", "WBS"),
    ("id", "Task ID"),
    ("label", "Task Name"),
    ("work_package", "Work Package"),
    ("storey_name", "Storey"),
    ("zone_name", "Zone"),
    ("ifc_class", "IFC Class"),
    ("predefined_type", "Predefined Type"),
    ("type_name", "Type"),
    ("material", "Material"),
    ("element_count", "Elements"),
    ("quantity", "Quantity"),
    ("unit", "Unit"),
    ("quantity_source", "Quantity Source"),
    ("duration_days", "Duration (d)"),
    ("crew", "Crew"),
    ("rate_id", "Rate"),
    ("confidence", "Confidence"),
    ("start_date", "Start"),
    ("finish_date", "Finish"),
    ("total_float", "Total Float"),
    ("free_float", "Free Float"),
    ("is_critical", "Critical"),
]


def _predecessor_text(task: dict[str, Any]) -> str:
    parts = []
    for link in task.get("predecessors") or []:
        lag = int(link.get("lag") or 0)
        suffix = f"{lag:+d}" if lag else ""
        parts.append(f"{link.get('id')}{link.get('type', 'FS')}{suffix}")
    return ", ".join(parts)


def _row(task: dict[str, Any]) -> list[Any]:
    row = [task.get(key) for key, _ in COLUMNS]
    row.append(_predecessor_text(task))
    row.append(";".join(task.get("element_ids") or []))
    return row


def _header() -> list[str]:
    return [title for _, title in COLUMNS] + ["Predecessors", "Source GlobalIds"]


def to_csv(schedule: dict[str, Any], project_name: str = "Schedule") -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_header())
    for task in schedule.get("tasks") or []:
        writer.writerow(_row(task))
    return buffer.getvalue().encode("utf-8-sig")


def to_xlsx(schedule: dict[str, Any], project_name: str = "Schedule") -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Schedule"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F2937")
    critical_fill = PatternFill("solid", fgColor="FEE2E2")

    header = _header()
    sheet.append(header)
    for column in range(1, len(header) + 1):
        cell = sheet.cell(row=1, column=column)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")

    for task in schedule.get("tasks") or []:
        sheet.append(_row(task))
        if task.get("is_critical"):
            for column in range(1, len(header) + 1):
                sheet.cell(row=sheet.max_row, column=column).fill = critical_fill

    widths = [10, 18, 46, 16, 14, 12, 18, 18, 22, 22, 10, 12, 8, 16, 12, 8, 18, 12,
              12, 12, 12, 12, 10, 30, 40]
    for index, width in enumerate(widths[: len(header)], start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"

    report_sheet = workbook.create_sheet("Run report")
    report_sheet.append(["Metric", "Value"])
    report_sheet.cell(row=1, column=1).font = Font(bold=True)
    report_sheet.cell(row=1, column=2).font = Font(bold=True)
    for key, value in _flatten(schedule.get("report") or {}):
        report_sheet.append([key, value])
    report_sheet.column_dimensions["A"].width = 46
    report_sheet.column_dimensions["B"].width = 60

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _flatten(data: Any, prefix: str = "") -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            rows.extend(_flatten(value, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(data, list):
        rows.append((prefix, ", ".join(str(item) for item in data[:20])))
    else:
        rows.append((prefix, data))
    return rows
