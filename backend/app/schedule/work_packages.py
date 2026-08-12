"""Maps elements onto work packages using config/work_packages.yaml."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from ..config import load_config
from ..util import as_float, as_text

DEFAULT_PACKAGES = (
    "Substructure",
    "Superstructure",
    "Envelope",
    "MEP",
    "Interior",
    "Finishes",
)


def matches_class(hierarchy: Any, ifc_class: str, wanted: str) -> bool:
    """is_a() semantics without needing the IFC file open."""
    if wanted == ifc_class:
        return True
    if isinstance(hierarchy, (list, tuple)):
        return wanted in hierarchy
    return False


class WorkPackageClassifier:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config if config is not None else load_config("work_packages")
        self.packages: list[str] = list(self.config.get("packages") or DEFAULT_PACKAGES)
        self.fallback: str = self.config.get("fallback_package") or self.packages[-1]
        self.rules: list[dict[str, Any]] = []
        for rule in self.config.get("rules") or []:
            match = dict(rule.get("match") or {})
            pattern = match.get("name_pattern")
            compiled = None
            if pattern:
                try:
                    compiled = re.compile(pattern)
                except re.error:
                    compiled = None
            predefined = match.get("predefined_type")
            if isinstance(predefined, str):
                predefined = [predefined]
            self.rules.append(
                {
                    "package": rule.get("package") or self.fallback,
                    "ifc_class": match.get("ifc_class"),
                    "predefined_type": {p.upper() for p in predefined} if predefined else None,
                    "name_regex": compiled,
                    "below_elevation": match.get("below_elevation"),
                }
            )

    def classify(self, row: dict[str, Any]) -> str:
        ifc_class = as_text(row.get("ifc_class"))
        hierarchy = row.get("class_hierarchy") or [ifc_class]
        predefined = as_text(row.get("predefined_type")).upper()
        elevation = as_float(row.get("storey_elevation"))
        searchable = " ".join(
            as_text(row.get(key))
            for key in ("name", "object_type", "type_name", "material")
        )

        for rule in self.rules:
            wanted_class = rule["ifc_class"]
            if wanted_class and not matches_class(hierarchy, ifc_class, wanted_class):
                continue
            wanted_predefined = rule["predefined_type"]
            if wanted_predefined and predefined not in wanted_predefined:
                continue
            regex = rule["name_regex"]
            if regex and not regex.search(searchable):
                continue
            threshold = rule["below_elevation"]
            if threshold is not None:
                if elevation is None or elevation >= float(threshold):
                    continue
            return rule["package"]
        return self.fallback

    def classify_frame(self, frame: pd.DataFrame) -> pd.Series:
        if frame.empty:
            return pd.Series([], dtype="object")
        return pd.Series(
            [self.classify(row) for row in frame.to_dict(orient="records")],
            index=frame.index,
            dtype="object",
        )

    def order_index(self, package: str, trade_order: list[str]) -> int:
        try:
            return trade_order.index(package)
        except ValueError:
            return len(trade_order)
