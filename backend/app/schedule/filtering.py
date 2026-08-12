"""Noise filtering: decide which elements are worth a task.

Everything here is driven by config/filters.yaml. The filter never silently
drops anything — each removal is recorded with a reason so the run report can
tell the user exactly what was left out.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..config import load_config
from .work_packages import matches_class

# Reasons, kept as constants so the UI and tests can rely on them.
REASON_EXCLUDED_CLASS = "excluded_class"
REASON_NAME_PATTERN = "name_pattern"
REASON_ASSEMBLY_CHILD = "assembly_child"
REASON_BELOW_SIZE = "below_size_threshold"


@dataclass
class FilterReport:
    total_in: int = 0
    kept: int = 0
    removed: int = 0
    by_reason: dict[str, int] = field(default_factory=dict)
    by_reason_and_class: dict[str, dict[str, int]] = field(default_factory=dict)
    rolled_up_quantity: dict[str, float] = field(default_factory=dict)
    examples: dict[str, list[str]] = field(default_factory=dict)

    def record(self, reason: str, ifc_class: str, global_id: str) -> None:
        self.removed += 1
        self.by_reason[reason] = self.by_reason.get(reason, 0) + 1
        bucket = self.by_reason_and_class.setdefault(reason, {})
        bucket[ifc_class] = bucket.get(ifc_class, 0) + 1
        samples = self.examples.setdefault(reason, [])
        if len(samples) < 5:
            samples.append(global_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "elements_in": self.total_in,
            "elements_kept": self.kept,
            "elements_removed": self.removed,
            "removed_by_reason": self.by_reason,
            "removed_by_reason_and_class": self.by_reason_and_class,
            "rolled_up_quantity": {k: round(v, 3) for k, v in self.rolled_up_quantity.items()},
            "examples": self.examples,
        }


class ElementFilter:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config if config is not None else load_config("filters")
        self.excluded_classes: list[str] = list(self.config.get("excluded_classes") or [])
        self.overrides: dict[str, bool] = dict(self.config.get("schedulable_overrides") or {})
        self.collapse_assemblies: bool = bool(self.config.get("collapse_assemblies", True))
        self.aggregate_trivial_at_l5: bool = bool(
            self.config.get("aggregate_trivial_at_l5", True)
        )

        threshold = self.config.get("size_threshold") or {}
        self.size_enabled: bool = bool(threshold.get("enabled", True))
        self.min_volume: float | None = threshold.get("min_net_volume_m3")
        self.min_diagonal: float | None = threshold.get("min_bbox_diagonal_m")
        self.size_only_classes: list[str] = list(threshold.get("only_classes") or [])
        self.size_never_classes: list[str] = list(threshold.get("never_filter_classes") or [])

        self.name_patterns = []
        for pattern in self.config.get("name_exclude_patterns") or []:
            try:
                self.name_patterns.append(re.compile(pattern))
            except re.error:
                continue

    # -- class rules -------------------------------------------------------

    def is_class_schedulable(self, ifc_class: str, hierarchy: Any) -> bool:
        """Overrides beat the exclusion list; the list matches subclasses too."""
        chain = hierarchy if isinstance(hierarchy, (list, tuple)) else [ifc_class]
        for candidate in chain:
            if candidate in self.overrides:
                return bool(self.overrides[candidate])
        for excluded in self.excluded_classes:
            if matches_class(chain, ifc_class, excluded):
                return False
        return True

    # -- size rule ---------------------------------------------------------

    def _size_applies(self, ifc_class: str, hierarchy: Any) -> bool:
        chain = hierarchy if isinstance(hierarchy, (list, tuple)) else [ifc_class]
        for never in self.size_never_classes:
            if matches_class(chain, ifc_class, never):
                return False
        if not self.size_only_classes:
            return True
        return any(matches_class(chain, ifc_class, only) for only in self.size_only_classes)

    def is_below_size(self, row: dict[str, Any]) -> bool:
        """True only when a populated measurement proves the element is trivial."""
        if not self.size_enabled:
            return False
        if not self._size_applies(row.get("ifc_class") or "", row.get("class_hierarchy")):
            return False

        volume = _number(row.get("qty_NetVolume")) or _number(row.get("qty_GrossVolume"))
        quantities = row.get("quantities") if isinstance(row.get("quantities"), dict) else {}
        diagonal = _number(quantities.get("BBoxDiagonal"))

        checks: list[bool] = []
        if self.min_volume is not None and volume is not None:
            checks.append(volume < float(self.min_volume))
        if self.min_diagonal is not None and diagonal is not None:
            checks.append(diagonal < float(self.min_diagonal))
        # No measurement at all -> we cannot prove it is trivial, so keep it.
        return bool(checks) and all(checks)

    # -- main entry point --------------------------------------------------

    def apply(self, frame: pd.DataFrame) -> tuple[pd.DataFrame, FilterReport]:
        """Return (kept elements, report). Input frame is not mutated."""
        report = FilterReport(total_in=int(len(frame)))
        if frame.empty:
            return frame.copy(), report

        rows = frame.to_dict(orient="records")
        assembly_ids = {
            row.get("global_id")
            for row in rows
            if row.get("is_assembly") and self._keeps_assembly(row)
        }

        keep_flags: list[bool] = []
        rolled: Counter = Counter()

        for row in rows:
            ifc_class = row.get("ifc_class") or ""
            hierarchy = row.get("class_hierarchy")
            global_id = str(row.get("global_id") or "")

            if not self.is_class_schedulable(ifc_class, hierarchy):
                report.record(REASON_EXCLUDED_CLASS, ifc_class, global_id)
                keep_flags.append(False)
                continue

            if self.name_patterns:
                searchable = " ".join(
                    str(row.get(key) or "") for key in ("name", "object_type", "type_name")
                )
                if any(pattern.search(searchable) for pattern in self.name_patterns):
                    report.record(REASON_NAME_PATTERN, ifc_class, global_id)
                    keep_flags.append(False)
                    continue

            if (
                self.collapse_assemblies
                and row.get("assembly_id")
                and row.get("assembly_id") in assembly_ids
            ):
                report.record(REASON_ASSEMBLY_CHILD, ifc_class, global_id)
                keep_flags.append(False)
                continue

            if self.is_below_size(row):
                report.record(REASON_BELOW_SIZE, ifc_class, global_id)
                volume = _number(row.get("qty_NetVolume"))
                if volume:
                    rolled["NetVolume"] += volume
                rolled["Count"] += 1
                keep_flags.append(False)
                continue

            keep_flags.append(True)

        report.rolled_up_quantity = dict(rolled)
        kept = frame[pd.Series(keep_flags, index=frame.index)].copy()
        report.kept = int(len(kept))
        return kept, report

    def _keeps_assembly(self, row: dict[str, Any]) -> bool:
        return self.is_class_schedulable(row.get("ifc_class") or "", row.get("class_hierarchy"))


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric:  # NaN
        return None
    return numeric
