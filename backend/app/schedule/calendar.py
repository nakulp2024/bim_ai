"""Working calendar: maps working-day offsets to real dates."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

DEFAULT_WORK_DAYS = (0, 1, 2, 3, 4)  # Monday..Friday


class WorkCalendar:
    def __init__(
        self,
        start_date: date | None = None,
        work_days: list[int] | tuple[int, ...] | None = None,
        holidays: list[str | date] | None = None,
    ) -> None:
        days = tuple(sorted({int(d) % 7 for d in (work_days or DEFAULT_WORK_DAYS)}))
        self.work_days: tuple[int, ...] = days or DEFAULT_WORK_DAYS
        self.holidays: set[date] = set()
        for holiday in holidays or []:
            parsed = _to_date(holiday)
            if parsed:
                self.holidays.add(parsed)
        self.start_date = _to_date(start_date) or date.today()
        if not self.is_working_day(self.start_date):
            self.start_date = self.next_working_day(self.start_date)
        self._cache: list[date] = []

    # -- primitives --------------------------------------------------------

    def is_working_day(self, day: date) -> bool:
        return day.weekday() in self.work_days and day not in self.holidays

    def next_working_day(self, day: date) -> date:
        cursor = day
        for _ in range(400):
            if self.is_working_day(cursor):
                return cursor
            cursor += timedelta(days=1)
        raise ValueError("no working day found within a year; check work_days/holidays")

    # -- offset <-> date ---------------------------------------------------

    def date_for_offset(self, offset: int) -> date:
        """Working day ``offset`` (0-based) counted from the project start."""
        if offset < 0:
            offset = 0
        while len(self._cache) <= offset:
            if not self._cache:
                self._cache.append(self.start_date)
                continue
            self._cache.append(self.next_working_day(self._cache[-1] + timedelta(days=1)))
        return self._cache[offset]

    def finish_date(self, start_offset: int, duration_days: int) -> date:
        """Inclusive finish date of a task starting at ``start_offset``."""
        return self.date_for_offset(start_offset + max(1, duration_days) - 1)

    def as_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date.isoformat(),
            "work_days": list(self.work_days),
            "holidays": sorted(h.isoformat() for h in self.holidays),
            "days_per_week": len(self.work_days),
        }


def _to_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def calendar_from_config(
    config: dict[str, Any], overrides: dict[str, Any] | None = None
) -> WorkCalendar:
    section = dict((config or {}).get("calendar") or {})
    section.update({k: v for k, v in (overrides or {}).items() if v is not None})
    return WorkCalendar(
        start_date=_to_date(section.get("start_date")),
        work_days=section.get("work_days"),
        holidays=section.get("holidays"),
    )
