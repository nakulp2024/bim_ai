from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import settings


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    speckle_user_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar: Mapped[str | None] = mapped_column(String, nullable=True)
    speckle_access_token: Mapped[str] = mapped_column(String)
    speckle_refresh_token: Mapped[str | None] = mapped_column(String, nullable=True)
    speckle_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ScheduleUpload(Base):
    __tablename__ = "schedule_uploads"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    speckle_project_id: Mapped[str] = mapped_column(String, index=True)
    speckle_model_id: Mapped[str] = mapped_column(String, index=True)
    speckle_version_id: Mapped[str] = mapped_column(String, index=True)
    speckle_referenced_object: Mapped[str | None] = mapped_column(String, nullable=True)
    filename: Mapped[str] = mapped_column(String)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String)
    headers: Mapped[list[str]] = mapped_column(JSONB, default=list)
    sample_rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MappingProposal(Base):
    __tablename__ = "mapping_proposals"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    schedule_id: Mapped[str] = mapped_column(
        String, ForeignKey("schedule_uploads.id"), index=True
    )
    proposed: Mapped[dict[str, Any]] = mapped_column(JSONB)
    join_strategy: Mapped[str] = mapped_column(String)
    confidence: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    catalog_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    confirmed: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String, index=True)
    state: Mapped[str] = mapped_column(String, index=True)  # queued|running|ready|failed
    progress: Mapped[float | None] = mapped_column(Float, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ElementIndex(Base):
    """One row per IfcProduct/IfcProduct-equivalent in a Speckle version.

    Built from the catalog walk; powers row-to-element resolution.
    Keyed by (user_id, project_id, version_id) — different versions of the
    same model get distinct entries so we can re-stitch animations.
    """

    __tablename__ = "element_index"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    speckle_project_id: Mapped[str] = mapped_column(String, index=True)
    speckle_model_id: Mapped[str] = mapped_column(String, index=True)
    speckle_version_id: Mapped[str] = mapped_column(String, index=True)
    speckle_object_id: Mapped[str] = mapped_column(String, index=True)
    application_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    category: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    level_name: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    family: Mapped[str | None] = mapped_column(String, nullable=True)
    type_name: Mapped[str | None] = mapped_column(String, nullable=True)
    speckle_type: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)


class ScheduleElementLink(Base):
    """Resolved (schedule row → speckle element) pairs."""

    __tablename__ = "schedule_element_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_id: Mapped[str] = mapped_column(
        String, ForeignKey("schedule_uploads.id"), index=True
    )
    task_id: Mapped[str] = mapped_column(String, index=True)
    speckle_object_id: Mapped[str] = mapped_column(String, index=True)
    application_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String)  # 'deterministic' | 'ai'
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


class Animation(Base):
    __tablename__ = "animations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    schedule_id: Mapped[str] = mapped_column(
        String, ForeignKey("schedule_uploads.id"), index=True
    )
    script: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


engine = create_async_engine(settings.database_url, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:  # type: ignore[misc]
    async with SessionLocal() as session:
        yield session
