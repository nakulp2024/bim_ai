"""Exports: every format must round-trip the schedule and the GlobalIds."""

from __future__ import annotations

import csv
import io
import json
from xml.etree import ElementTree as ET

import pytest

from app.exports import FORMATS, to_csv, to_json_package, to_msproject_xml, to_p6_xer, to_xlsx
from app.exports.msproject import MSPDI_NS
from app.schedule.pipeline import ScheduleOptions, generate_schedule


@pytest.fixture(scope="module")
def schedule(request):
    frame = request.getfixturevalue("elements")
    result = generate_schedule(frame, ScheduleOptions(level="L3", start_date="2026-09-01"))
    return result.as_dict()


@pytest.mark.parametrize("fmt", sorted(FORMATS))
def test_every_registered_format_produces_bytes(schedule, fmt):
    _media_type, extension, writer = FORMATS[fmt]
    payload = writer(schedule, "Sample Tower")
    assert isinstance(payload, bytes)
    assert len(payload) > 200
    assert extension


# --- CSV ------------------------------------------------------------------


def test_csv_has_one_row_per_task_with_source_ids(schedule):
    text = to_csv(schedule, "Sample Tower").decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == len(schedule["tasks"])
    assert rows[0]["Task Name"] == schedule["tasks"][0]["label"]
    first = schedule["tasks"][0]
    assert rows[0]["Source GlobalIds"].split(";") == first["element_ids"]
    assert rows[0]["Duration (d)"] == str(first["duration_days"])


def test_csv_encodes_predecessors_with_type_and_lag(schedule):
    linked = next(task for task in schedule["tasks"] if task["predecessors"])
    text = to_csv(schedule, "S").decode("utf-8-sig")
    row = next(
        r for r in csv.DictReader(io.StringIO(text)) if r["Task ID"] == linked["id"]
    )
    for link in linked["predecessors"]:
        assert link["id"] in row["Predecessors"]
        assert link["type"] in row["Predecessors"]


# --- XLSX -----------------------------------------------------------------


def test_xlsx_has_a_schedule_and_a_report_sheet(schedule):
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(to_xlsx(schedule, "Sample Tower")))
    assert workbook.sheetnames == ["Schedule", "Run report"]
    sheet = workbook["Schedule"]
    assert sheet.max_row == len(schedule["tasks"]) + 1
    assert sheet.cell(row=1, column=3).value == "Task Name"
    assert sheet.freeze_panes == "A2"
    assert workbook["Run report"].max_row > 5


# --- MS Project -----------------------------------------------------------


def test_mspdi_is_valid_xml_with_tasks_and_links(schedule):
    root = ET.fromstring(to_msproject_xml(schedule, "Sample Tower"))
    assert root.tag == f"{{{MSPDI_NS}}}Project"

    tasks = root.findall(f".//{{{MSPDI_NS}}}Task")
    assert len(tasks) == len(schedule["tasks"])

    uids = {task.findtext(f"{{{MSPDI_NS}}}UID") for task in tasks}
    assert len(uids) == len(tasks)

    links = root.findall(f".//{{{MSPDI_NS}}}PredecessorLink")
    expected = sum(len(task["predecessors"]) for task in schedule["tasks"])
    assert len(links) == expected
    for link in links:
        assert link.findtext(f"{{{MSPDI_NS}}}PredecessorUID") in uids
        assert link.findtext(f"{{{MSPDI_NS}}}Type") in {"0", "1", "2", "3"}


def test_mspdi_carries_global_ids_in_notes(schedule):
    root = ET.fromstring(to_msproject_xml(schedule, "Sample Tower"))
    first_task = root.find(f".//{{{MSPDI_NS}}}Task")
    notes = first_task.findtext(f"{{{MSPDI_NS}}}Notes")
    assert schedule["tasks"][0]["element_ids"][0] in notes


def test_mspdi_calendar_matches_the_work_week(schedule):
    root = ET.fromstring(to_msproject_xml(schedule, "Sample Tower"))
    days = root.findall(f".//{{{MSPDI_NS}}}WeekDay")
    assert len(days) == 7
    working = [d for d in days if d.findtext(f"{{{MSPDI_NS}}}DayWorking") == "1"]
    assert len(working) == len(schedule["calendar"]["work_days"])


# --- Primavera P6 ---------------------------------------------------------


def _xer_tables(payload: str) -> dict[str, list[list[str]]]:
    tables: dict[str, list[list[str]]] = {}
    current = None
    for line in payload.splitlines():
        parts = line.split("\t")
        if parts[0] == "%T":
            current = parts[1]
            tables[current] = []
        elif parts[0] == "%R" and current:
            tables[current].append(parts[1:])
    return tables


def test_xer_has_the_expected_table_structure(schedule):
    payload = to_p6_xer(schedule, "Sample Tower").decode("utf-8")
    assert payload.startswith("ERMHDR\t")
    assert payload.rstrip().endswith("%E")

    tables = _xer_tables(payload)
    assert {"PROJECT", "CALENDAR", "PROJWBS", "TASK", "TASKPRED"} <= set(tables)
    assert len(tables["PROJECT"]) == 1
    assert len(tables["TASK"]) == len(schedule["tasks"])
    assert len(tables["TASKPRED"]) == sum(
        len(task["predecessors"]) for task in schedule["tasks"]
    )


def test_xer_task_ids_are_unique_and_referenced_by_links(schedule):
    tables = _xer_tables(to_p6_xer(schedule, "S").decode("utf-8"))
    task_ids = {row[0] for row in tables["TASK"]}
    assert len(task_ids) == len(tables["TASK"])
    for row in tables["TASKPRED"]:
        assert row[1] in task_ids  # task_id
        assert row[2] in task_ids  # pred_task_id
        assert row[5].startswith("PR_")


def test_xer_wbs_nodes_are_parented_correctly(schedule):
    tables = _xer_tables(to_p6_xer(schedule, "S").decode("utf-8"))
    wbs_ids = {row[0] for row in tables["PROJWBS"]}
    for row in tables["PROJWBS"]:
        parent = row[2]
        if parent:
            assert parent in wbs_ids
    for row in tables["TASK"]:
        assert row[2] in wbs_ids


def test_xer_preserves_global_ids(schedule):
    tables = _xer_tables(to_p6_xer(schedule, "S").decode("utf-8"))
    assert "IFCSOURCE" in tables
    assert len(tables["IFCSOURCE"]) == len(schedule["tasks"])
    assert schedule["tasks"][0]["element_ids"][0] in tables["IFCSOURCE"][0][2]


def test_xer_never_contains_raw_tabs_or_newlines_in_values(schedule):
    payload = to_p6_xer(schedule, "S").decode("utf-8")
    for line in payload.splitlines():
        if line.startswith("%R"):
            # Every %R row must have exactly the field count of its table.
            assert "\n" not in line


# --- JSON -----------------------------------------------------------------


def test_json_package_is_complete(schedule):
    package = json.loads(to_json_package(schedule, "Sample Tower"))
    assert package["schema"] == "ifc-schedule/1.0"
    assert package["project"]["name"] == "Sample Tower"
    assert len(package["tasks"]) == len(schedule["tasks"])
    assert package["links"] == schedule["links"]
    assert package["report"]

    task = package["tasks"][0]
    source = schedule["tasks"][0]
    assert task["source_global_ids"] == source["element_ids"]
    assert task["duration_days"] == source["duration_days"]
    assert task["dates"]["early_start"] == source["start_date"]
    assert task["float"]["critical"] == source["is_critical"]
    assert task["quantity"]["source"] in ("base_quantity", "derived", "mixed", "none")


def test_json_is_the_lossless_format_for_4d_linking(schedule):
    package = json.loads(to_json_package(schedule, "S"))
    exported = {gid for task in package["tasks"] for gid in task["source_global_ids"]}
    original = {gid for task in schedule["tasks"] for gid in task["element_ids"]}
    assert exported == original


# --- edge cases -----------------------------------------------------------


@pytest.mark.parametrize("fmt", sorted(FORMATS))
def test_empty_schedule_does_not_break_any_exporter(fmt):
    empty = {"tasks": [], "links": [], "calendar": {}, "report": {}, "options": {}}
    _media, _ext, writer = FORMATS[fmt]
    assert isinstance(writer(empty, "Empty"), bytes)
