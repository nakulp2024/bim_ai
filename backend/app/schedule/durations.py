"""Duration engine: task group + rate library -> duration in working days.

    duration = ceil(quantity / (output_per_crew_day * crew))  clamped to min

The fallback chain is explicit and every result reports which link of the chain
produced it, which is what drives the task's confidence flag.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from ..config import load_config
from ..ifc.model import UNIT_QUANTITY_PREFERENCE
from .lod import TaskGroup
from .work_packages import matches_class

VALID_UNITS = ("m3", "m2", "m", "ea")

# Which link of the fallback chain maps to which confidence.
CONFIDENCE_BY_SOURCE = {
    "type_rate": "high",
    "class_rate": "medium",
    "global_default": "low",
    "count_fallback": "low",
}


@dataclass
class Rate:
    id: str
    unit: str
    output_per_crew_day: float
    default_crew: int
    min_duration_days: int
    ifc_class: str | None = None
    predefined_types: set[str] | None = None
    material_regex: re.Pattern | None = None

    @property
    def specificity(self) -> str:
        """'type_rate' when the rule pins down more than just the class."""
        if self.material_regex is not None or self.predefined_types:
            return "type_rate"
        return "class_rate"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "unit": self.unit,
            "output_per_crew_day": self.output_per_crew_day,
            "default_crew": self.default_crew,
            "min_duration_days": self.min_duration_days,
            "ifc_class": self.ifc_class,
            "predefined_types": sorted(self.predefined_types) if self.predefined_types else None,
            "material_pattern": self.material_regex.pattern if self.material_regex else None,
        }


@dataclass
class DurationResult:
    duration_days: int
    quantity: float | None
    quantity_key: str | None
    unit: str
    rate_id: str
    rate_source: str
    confidence: str
    crew: int
    output_per_crew_day: float
    notes: list[str]


def _compile_rate(raw: dict[str, Any], index: int) -> Rate | None:
    match = raw.get("match") or {}
    unit = str(raw.get("unit") or "ea").lower()
    if unit not in VALID_UNITS:
        return None
    predefined = match.get("predefined_type")
    if isinstance(predefined, str):
        predefined = [predefined]
    pattern = match.get("material_pattern")
    compiled = None
    if pattern:
        try:
            compiled = re.compile(pattern)
        except re.error:
            compiled = None
    try:
        output = float(raw.get("output_per_crew_day"))
    except (TypeError, ValueError):
        return None
    # A zero or negative output is a config error, not a rate: reject the rule
    # so the fallback chain moves on instead of dividing by nothing.
    if not output > 0:
        return None

    try:
        return Rate(
            id=str(raw.get("id") or f"rule-{index}"),
            unit=unit,
            output_per_crew_day=output,
            default_crew=max(1, int(raw.get("default_crew") or 1)),
            min_duration_days=max(1, int(raw.get("min_duration_days") or 1)),
            ifc_class=match.get("ifc_class"),
            predefined_types={p.upper() for p in predefined} if predefined else None,
            material_regex=compiled,
        )
    except (TypeError, ValueError):
        return None


class RateLibrary:
    """Loads config/rates.yaml and resolves a rate for a task group."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config if config is not None else load_config("rates")
        self.rules: list[Rate] = []
        for index, raw in enumerate(self.config.get("rules") or []):
            rate = _compile_rate(raw, index)
            if rate is not None:
                self.rules.append(rate)
        self.default = _compile_rate(
            {"id": "default", **(self.config.get("default") or {})}, -1
        ) or Rate("default", "ea", 10.0, 1, 1)
        self.count_fallback = _compile_rate(
            {"id": "count_fallback", **(self.config.get("count_fallback") or {})}, -2
        ) or Rate("count_fallback", "ea", 20.0, 1, 1)

    # -- lookup ------------------------------------------------------------

    def candidates(self, group: TaskGroup, hierarchy: list[str] | None = None) -> list[Rate]:
        """Rules matching this group, most specific first."""
        ifc_class = group.ifc_class or ""
        chain = hierarchy or [ifc_class]
        predefined = (group.predefined_type or "").upper()
        searchable = " ".join(
            str(x) for x in (group.material, group.type_name, group.label) if x
        )

        matched: list[tuple[int, Rate]] = []
        for rate in self.rules:
            if rate.ifc_class and not matches_class(chain, ifc_class, rate.ifc_class):
                continue
            if rate.predefined_types and predefined not in rate.predefined_types:
                continue
            if rate.material_regex and not rate.material_regex.search(searchable):
                continue
            score = 0
            if rate.material_regex:
                score += 2
            if rate.predefined_types:
                score += 1
            matched.append((score, rate))
        matched.sort(key=lambda pair: -pair[0])
        return [rate for _, rate in matched]

    def as_dict(self) -> dict[str, Any]:
        return {
            "default": self.default.as_dict(),
            "count_fallback": self.count_fallback.as_dict(),
            "rules": [rate.as_dict() for rate in self.rules],
        }


def _quantity_for_unit(group: TaskGroup, unit: str) -> tuple[float | None, str | None]:
    for key in UNIT_QUANTITY_PREFERENCE.get(unit, ()):
        value = group.quantities.get(key)
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if numeric > 0:
            return numeric, key
    return None, None


def compute_duration(
    group: TaskGroup,
    library: RateLibrary,
    hierarchy: list[str] | None = None,
    crew_overrides: dict[str, int] | None = None,
) -> DurationResult:
    """Walk the fallback chain until a rate produces a usable quantity."""
    notes: list[str] = []
    attempts: list[tuple[Rate, str]] = [
        (rate, rate.specificity) for rate in library.candidates(group, hierarchy)
    ]
    attempts.append((library.default, "global_default"))
    attempts.append((library.count_fallback, "count_fallback"))

    for rate, source in attempts:
        quantity, quantity_key = _quantity_for_unit(group, rate.unit)
        if quantity is None:
            if source in ("type_rate", "class_rate"):
                notes.append(f"rate '{rate.id}' skipped: no {rate.unit} quantity available")
            continue
        crew = max(1, int((crew_overrides or {}).get(rate.id, rate.default_crew)))
        throughput = rate.output_per_crew_day * crew
        if throughput <= 0:
            notes.append(f"rate '{rate.id}' skipped: non-positive output")
            continue
        duration = max(rate.min_duration_days, int(math.ceil(quantity / throughput)))
        confidence = CONFIDENCE_BY_SOURCE[source]
        if group.quantity_source in ("derived", "mixed") and confidence == "high":
            confidence = "medium"
            notes.append("confidence lowered: quantities are geometry-derived")
        elif group.quantity_source == "none":
            confidence = "low"
        return DurationResult(
            duration_days=duration,
            quantity=round(quantity, 4),
            quantity_key=quantity_key,
            unit=rate.unit,
            rate_id=rate.id,
            rate_source=source,
            confidence=confidence,
            crew=crew,
            output_per_crew_day=rate.output_per_crew_day,
            notes=notes,
        )

    # count_fallback always has a Count quantity in practice; this is the
    # belt-and-braces path for a group with literally no quantities at all.
    notes.append("no quantity of any kind; defaulted to minimum duration")
    return DurationResult(
        duration_days=max(1, library.count_fallback.min_duration_days),
        quantity=None,
        quantity_key=None,
        unit=library.count_fallback.unit,
        rate_id=library.count_fallback.id,
        rate_source="count_fallback",
        confidence="low",
        crew=library.count_fallback.default_crew,
        output_per_crew_day=library.count_fallback.output_per_crew_day,
        notes=notes,
    )
