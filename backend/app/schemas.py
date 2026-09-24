"""Request/response models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(default="Untitled project", max_length=200)


class ScheduleRequest(BaseModel):
    level: Literal["L1", "L2", "L3", "L4", "L5"] = "L3"
    zone_split: str | None = None
    start_date: str | None = None
    work_days: list[int] | None = None
    holidays: list[str] = Field(default_factory=list)
    crew_overrides: dict[str, int] = Field(default_factory=dict)
    llm_enabled: bool = False


class LodPreviewRequest(BaseModel):
    zone_split: str | None = None


class TaskUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=300)
    duration_days: int | None = Field(default=None, ge=0, le=3650)
    crew: int | None = Field(default=None, ge=1, le=500)
    work_package: str | None = None
    predecessors: list[LinkIn] | None = None


class LinkIn(BaseModel):
    id: str
    type: Literal["FS", "SS", "FF", "SF"] = "FS"
    lag: int = 0


class LinkCreate(BaseModel):
    predecessor_id: str
    successor_id: str
    type: Literal["FS", "SS", "FF", "SF"] = "FS"
    lag: int = 0


class RateRuleIn(BaseModel):
    id: str
    unit: Literal["m3", "m2", "m", "ea"] | None = None
    output_per_crew_day: float | None = Field(default=None, gt=0)
    default_crew: int | None = Field(default=None, ge=1, le=500)
    min_duration_days: int | None = Field(default=None, ge=0, le=365)


class RatesUpdate(BaseModel):
    rules: list[RateRuleIn] = Field(default_factory=list)
    default: dict[str, Any] | None = None
    count_fallback: dict[str, Any] | None = None
    recalculate: bool = True


class CalendarUpdate(BaseModel):
    start_date: str | None = None
    work_days: list[int] | None = None
    holidays: list[str] | None = None


TaskUpdate.model_rebuild()


# --- progress --------------------------------------------------------------


class ProgressEntryIn(BaseModel):
    task_id: str
    percent_complete: float | None = Field(default=None, ge=0, le=100)
    quantity_placed: float | None = Field(default=None, ge=0)
    actual_start: str | None = None
    actual_finish: str | None = None
    note: str | None = Field(default=None, max_length=2000)


class ProgressReport(BaseModel):
    """A batch of task updates, reported together (e.g. one daily report)."""

    entries: list[ProgressEntryIn] = Field(min_length=1, max_length=5000)
    reported_on: str | None = None


class BaselineCreate(BaseModel):
    name: str | None = Field(default=None, max_length=200)


class DataDateUpdate(BaseModel):
    data_date: str
