"""End-to-end: element frame -> filtered -> grouped -> priced -> sequenced -> CPM."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..config import load_config
from .calendar import WorkCalendar, calendar_from_config
from .cpm import CpmTask, calculate
from .durations import RateLibrary, compute_duration
from .filtering import ElementFilter
from .lod import TaskGroup, group_elements
from .sequencing import SequencingEngine
from .work_packages import WorkPackageClassifier

log = logging.getLogger(__name__)

ProgressFn = Callable[[float, str], None]


@dataclass
class ScheduleOptions:
    level: str = "L3"
    zone_split: str | None = None
    start_date: str | None = None
    work_days: list[int] | None = None
    holidays: list[str] = field(default_factory=list)
    crew_overrides: dict[str, int] = field(default_factory=dict)
    rate_overrides: dict[str, Any] | None = None
    llm_enabled: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ScheduleOptions:
        data = data or {}
        return cls(
            level=str(data.get("level") or "L3").upper(),
            zone_split=data.get("zone_split") or None,
            start_date=data.get("start_date") or None,
            work_days=data.get("work_days") or None,
            holidays=list(data.get("holidays") or []),
            crew_overrides={str(k): int(v) for k, v in (data.get("crew_overrides") or {}).items()},
            rate_overrides=data.get("rate_overrides") or None,
            llm_enabled=bool(data.get("llm_enabled", False)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "zone_split": self.zone_split,
            "start_date": self.start_date,
            "work_days": self.work_days,
            "holidays": self.holidays,
            "crew_overrides": self.crew_overrides,
            "llm_enabled": self.llm_enabled,
        }


@dataclass
class ScheduleResult:
    tasks: list[dict[str, Any]]
    links: list[dict[str, Any]]
    calendar: dict[str, Any]
    report: dict[str, Any]
    options: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "tasks": self.tasks,
            "links": self.links,
            "calendar": self.calendar,
            "report": self.report,
            "options": self.options,
        }


def make_task_id(group: TaskGroup, index: int) -> str:
    """Stable id derived from the grouping key, so edits survive a regenerate."""
    digest = hashlib.sha1("|".join(str(part) for part in group.key).encode()).hexdigest()[:10]
    return f"T{index + 1:05d}-{digest}"


def assign_wbs_codes(tasks: list[dict[str, Any]]) -> None:
    """Number tasks 1, 1.1, 1.1.2 ... from their wbs_path.

    A trailing leaf number is only appended when several tasks share the same
    path; otherwise the path's own code is already unique and an extra level
    would just make every code one segment longer to read.
    """
    node_counters: dict[tuple[str, ...], int] = {}
    node_codes: dict[tuple[str, ...], str] = {}

    def code_for(path: tuple[str, ...]) -> str:
        if not path:
            return ""
        if path in node_codes:
            return node_codes[path]
        parent = path[:-1]
        parent_code = code_for(parent)
        node_counters[parent] = node_counters.get(parent, 0) + 1
        index = node_counters[parent]
        code = f"{parent_code}.{index}" if parent_code else str(index)
        node_codes[path] = code
        return code

    shared: dict[tuple[str, ...], int] = {}
    for task in tasks:
        path = tuple(task.get("wbs_path") or [])
        shared[path] = shared.get(path, 0) + 1

    leaf_counters: dict[tuple[str, ...], int] = {}
    for task in tasks:
        path = tuple(task.get("wbs_path") or [])
        if not path:
            task["wbs_code"] = ""
            continue
        code = code_for(path)
        if shared[path] > 1:
            leaf_counters[path] = leaf_counters.get(path, 0) + 1
            code = f"{code}.{leaf_counters[path]}"
        task["wbs_code"] = code


def apply_cpm(
    tasks: list[dict[str, Any]],
    links: list[dict[str, Any]],
    calendar: WorkCalendar,
) -> dict[str, Any]:
    """Run CPM over task rows and stamp dates/float back onto them in place."""
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

    cpm_tasks = [
        CpmTask(
            id=task["id"],
            duration=max(0, int(task.get("duration_days") or 0)),
            predecessors=predecessors[task["id"]],
        )
        for task in tasks
    ]
    result = calculate(cpm_tasks)

    for task in tasks:
        computed = result.tasks[task["id"]]
        duration = max(1, int(task.get("duration_days") or 1))
        task["early_start_offset"] = computed.early_start
        task["early_finish_offset"] = computed.early_finish
        task["late_start_offset"] = computed.late_start
        task["late_finish_offset"] = computed.late_finish
        task["total_float"] = computed.total_float
        task["free_float"] = computed.free_float
        task["is_critical"] = bool(computed.is_critical)
        task["start_date"] = calendar.date_for_offset(computed.early_start).isoformat()
        task["finish_date"] = calendar.finish_date(computed.early_start, duration).isoformat()
        task["late_start_date"] = calendar.date_for_offset(max(0, computed.late_start)).isoformat()
        task["late_finish_date"] = calendar.finish_date(
            max(0, computed.late_start), duration
        ).isoformat()
        task["predecessors"] = predecessors[task["id"]]

    # Drop links CPM rejected so stored state matches what was calculated.
    rejected = {(d["from"], d["to"]) for d in result.dropped_links}
    rejected |= {(c["from"], c["to"]) for c in result.cycles_broken}
    surviving = [
        link
        for link in links
        if (link.get("predecessor_id"), link.get("successor_id")) not in rejected
    ]
    links[:] = surviving

    return {
        "project_duration_days": result.project_duration,
        "critical_task_count": len(result.critical_path),
        "cycles_broken": result.cycles_broken,
        "dropped_links": result.dropped_links,
        "finish_date": calendar.date_for_offset(max(0, result.project_duration - 1)).isoformat(),
    }


def generate_schedule(
    frame: pd.DataFrame,
    options: ScheduleOptions,
    parse_report: dict[str, Any] | None = None,
    progress: ProgressFn | None = None,
    configs: dict[str, Any] | None = None,
) -> ScheduleResult:
    """Run the deterministic pipeline end to end."""
    configs = configs or {}
    filters_config = configs.get("filters") or load_config("filters")
    work_packages_config = configs.get("work_packages") or load_config("work_packages")
    rates_config = configs.get("rates") or load_config("rates")
    sequencing_config = configs.get("sequencing") or load_config("sequencing")
    if options.rate_overrides:
        rates_config = _merge_rate_overrides(rates_config, options.rate_overrides)

    def emit(fraction: float, message: str) -> None:
        if progress:
            try:
                progress(fraction, message)
            except Exception:
                pass

    classifier = WorkPackageClassifier(work_packages_config)

    emit(0.05, "Classifying work packages")
    working = frame.copy()
    if not working.empty:
        working["work_package"] = classifier.classify_frame(working)

    emit(0.15, "Filtering noise")
    element_filter = ElementFilter(filters_config)
    kept, filter_report = element_filter.apply(working)

    emit(0.30, f"Grouping at {options.level}")
    groups = group_elements(
        kept,
        level=options.level,
        zone_split=options.zone_split,
        classifier=classifier,
        filters_config=filters_config,
    )

    emit(0.50, "Calculating durations")
    library = RateLibrary(rates_config)
    hierarchy_by_class = _hierarchy_index(working)
    tasks: list[dict[str, Any]] = []
    confidence_counts = {"high": 0, "medium": 0, "low": 0}

    for index, group in enumerate(groups):
        duration = compute_duration(
            group,
            library,
            hierarchy=hierarchy_by_class.get(group.ifc_class or ""),
            crew_overrides=options.crew_overrides,
        )
        confidence_counts[duration.confidence] += 1
        task = group.as_dict()
        task.update(
            {
                "id": make_task_id(group, index),
                "duration_days": duration.duration_days,
                "quantity": duration.quantity,
                "quantity_key": duration.quantity_key,
                "unit": duration.unit,
                "rate_id": duration.rate_id,
                "rate_source": duration.rate_source,
                "confidence": duration.confidence,
                "crew": duration.crew,
                "output_per_crew_day": duration.output_per_crew_day,
                "user_edited": False,
                "duration_notes": duration.notes,
            }
        )
        tasks.append(task)

    assign_wbs_codes(tasks)

    emit(0.70, "Applying sequencing rules")
    engine = SequencingEngine(sequencing_config)
    links = [link.as_dict() for link in engine.build_links(tasks)]

    emit(0.85, "Running CPM")
    calendar = calendar_from_config(
        sequencing_config,
        {
            "start_date": options.start_date,
            "work_days": options.work_days,
            "holidays": options.holidays or None,
        },
    )
    cpm_report = apply_cpm(tasks, links, calendar)

    if options.llm_enabled:
        emit(0.92, "Applying optional LLM enrichment")
        try:
            from ..llm.enrich import enrich_schedule

            enrich_schedule(tasks, kept)
        except Exception as exc:  # never let the optional layer break a run
            log.warning("LLM enrichment skipped: %s", exc)

    emit(0.98, f"{len(tasks)} tasks generated")
    report = {
        "parse": parse_report or {},
        "filter": filter_report.as_dict(),
        "grouping": {
            "level": options.level,
            "zone_split": options.zone_split,
            "task_count": len(tasks),
            "elements_in_tasks": sum(task["element_count"] for task in tasks),
            "aggregated_trivial_groups": sum(
                1 for task in tasks if task.get("aggregated_trivial")
            ),
        },
        "durations": {
            "confidence": confidence_counts,
            "quantity_coverage_pct": _coverage(tasks),
            "by_rate_source": _count_by(tasks, "rate_source"),
        },
        "sequencing": {
            "link_count": len(links),
            "by_origin": _count_by(links, "origin"),
        },
        "cpm": cpm_report,
    }

    return ScheduleResult(
        tasks=tasks,
        links=links,
        calendar=calendar.as_dict(),
        report=report,
        options=options.as_dict(),
    )


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _hierarchy_index(frame: pd.DataFrame) -> dict[str, list[str]]:
    if frame.empty or "class_hierarchy" not in frame:
        return {}
    index: dict[str, list[str]] = {}
    for ifc_class, hierarchy in zip(
        frame["ifc_class"], frame["class_hierarchy"], strict=False
    ):
        if ifc_class not in index and isinstance(hierarchy, (list, tuple)):
            index[str(ifc_class)] = list(hierarchy)
    return index


def _merge_rate_overrides(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Apply per-project rate edits from the UI onto the packaged library."""
    merged = {**base}
    if "default" in overrides:
        merged["default"] = {**(base.get("default") or {}), **overrides["default"]}
    if "count_fallback" in overrides:
        merged["count_fallback"] = {
            **(base.get("count_fallback") or {}),
            **overrides["count_fallback"],
        }
    by_id = {str(rule.get("id")): dict(rule) for rule in base.get("rules") or []}
    for rule in overrides.get("rules") or []:
        rule_id = str(rule.get("id"))
        if rule_id in by_id:
            by_id[rule_id].update(rule)
        else:
            by_id[rule_id] = dict(rule)
    merged["rules"] = list(by_id.values())
    return merged


def _coverage(tasks: list[dict[str, Any]]) -> float:
    if not tasks:
        return 0.0
    measured = sum(1 for task in tasks if task.get("quantity_source") != "none")
    return round(100.0 * measured / len(tasks), 2)


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts
