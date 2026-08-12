"""SQLite persistence via SQLAlchemy.

Element frames are large, so they live on disk as gzipped JSON next to the
uploaded IFC; the database holds project metadata, the generated schedule and
per-project rate overrides.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

from .config import get_settings
from .util import normalize_frame


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    ifc_filename = Column(String(400))
    ifc_path = Column(String(800))
    ifc_schema = Column(String(40))
    element_count = Column(Integer, default=0)

    status = Column(String(40), default="created")  # created|parsing|parsed|scheduling|ready|failed
    parse_report = Column(JSON, default=dict)
    profile = Column(JSON, default=dict)
    rate_overrides = Column(JSON, default=dict)
    schedule_options = Column(JSON, default=dict)
    error = Column(Text)

    schedule = relationship(
        "ScheduleRecord",
        back_populates="project",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "ifc_filename": self.ifc_filename,
            "ifc_schema": self.ifc_schema,
            "element_count": self.element_count,
            "status": self.status,
            "error": self.error,
            "has_schedule": self.schedule is not None,
        }


class ScheduleRecord(Base):
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), unique=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    level = Column(String(4), default="L3")
    zone_split = Column(String(120))
    tasks = Column(JSON, default=list)
    links = Column(JSON, default=list)
    calendar = Column(JSON, default=dict)
    report = Column(JSON, default=dict)
    options = Column(JSON, default=dict)
    project_duration_days = Column(Float, default=0.0)

    project = relationship("Project", back_populates="schedule")

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "level": self.level,
            "zone_split": self.zone_split,
            "tasks": self.tasks or [],
            "links": self.links or [],
            "calendar": self.calendar or {},
            "report": self.report or {},
            "options": self.options or {},
            "project_duration_days": self.project_duration_days,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class JobRecord(Base):
    __tablename__ = "jobs"

    id = Column(String(40), primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"))
    kind = Column(String(40))  # parse | schedule
    status = Column(String(20), default="queued")  # queued|running|done|failed
    progress = Column(Float, default=0.0)
    message = Column(String(400), default="")
    error = Column(Text)
    result = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "kind": self.kind,
            "status": self.status,
            "progress": round(float(self.progress or 0.0), 4),
            "message": self.message or "",
            "error": self.error,
            "result": self.result or {},
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        settings.ensure_dirs()
        _engine = create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False}
            if settings.database_url.startswith("sqlite")
            else {},
            future=True,
        )
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def init_db() -> None:
    Base.metadata.create_all(bind=get_engine())


def get_sessionmaker() -> sessionmaker:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    factory = get_sessionmaker()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Used by tests to rebind after changing IFCSCHED_DATABASE_URL."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


# --------------------------------------------------------------------------
# element frame storage
# --------------------------------------------------------------------------


def elements_path(project_id: int) -> Path:
    settings = get_settings()
    directory = settings.project_dir / str(project_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "elements.json.gz"


def save_elements(project_id: int, frame: pd.DataFrame) -> Path:
    path = elements_path(project_id)
    payload = frame.to_dict(orient="records")
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, default=_json_default)
    return path


def load_elements(project_id: int) -> pd.DataFrame:
    path = elements_path(project_id)
    if not path.exists():
        return pd.DataFrame()
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    return normalize_frame(pd.DataFrame(payload))


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if hasattr(value, "item"):  # numpy scalars
        try:
            return value.item()
        except Exception:
            return str(value)
    return str(value)
