"""Resolve schedule rows to Speckle element IDs.

Runs after the user confirms the column mapping. Reads the CSV from disk,
extracts roles from the confirmed mapping, then performs a deterministic SQL
join against ElementIndex.
"""
from __future__ import annotations

import traceback
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import delete, select

from ..celery_app import celery
from ..db import ElementIndex, Job, MappingProposal, ScheduleElementLink, ScheduleUpload
from ..db_sync import SyncSessionLocal
from ..schedules.ingest import read_schedule


def _update_job(session, job: Job, **fields) -> None:
    for k, v in fields.items():
        setattr(job, k, v)
    job.updated_at = datetime.now(timezone.utc)
    session.add(job)
    session.commit()


def _role_to_column(mapping: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in mapping:
        role = m.get("role")
        col = m.get("column")
        if role and col and role != "ignored":
            # First column wins per role.
            out.setdefault(role, col)
    return out


def _resolve(
    df: pd.DataFrame,
    role_col: dict[str, str],
    join_strategy: str,
    elements: list[ElementIndex],
    mapping: list[dict[str, Any]],
) -> tuple[list[tuple[str, str]], list[dict[str, Any]]]:
    """Return (links, unmatched_samples).

    links is a list of (task_id, speckle_object_id).
    """
    task_col = role_col.get("task_id")
    if not task_col or task_col not in df.columns:
        # Fall back to row index.
        df = df.copy()
        df["__task_id"] = [f"row-{i}" for i in range(len(df))]
        task_col = "__task_id"

    links: list[tuple[str, str]] = []
    unmatched: list[dict[str, Any]] = []

    if join_strategy == "application_id":
        join_col = role_col.get("join_key")
        if not join_col or join_col not in df.columns:
            return [], df.head(5).to_dict(orient="records")
        by_app: dict[str, list[ElementIndex]] = defaultdict(list)
        for el in elements:
            if el.application_id:
                by_app[el.application_id].append(el)
        for _, row in df.iterrows():
            key = str(row.get(join_col) or "").strip()
            if not key:
                unmatched.append(row.to_dict())
                continue
            hits = by_app.get(key, [])
            if not hits:
                unmatched.append(row.to_dict())
                continue
            tid = str(row[task_col])
            for el in hits:
                links.append((tid, el.speckle_object_id))

    elif join_strategy in {"category_and_level", "type_and_level"}:
        # Find which column provides each side. The mapping may have a join_key
        # column with a speckle_property hint (e.g. 'category' or 'level.name')
        # — for simplicity, use any column whose name matches loosely.
        cat_col = _guess_column(df, mapping, ["category", "type", "family"])
        lvl_col = _guess_column(df, mapping, ["level", "floor", "storey"])
        if not cat_col or not lvl_col:
            return [], df.head(5).to_dict(orient="records")
        key_attr = "category" if join_strategy == "category_and_level" else "type_name"
        by_key: dict[tuple[str | None, str | None], list[ElementIndex]] = defaultdict(list)
        for el in elements:
            by_key[(getattr(el, key_attr), el.level_name)].append(el)
        for _, row in df.iterrows():
            cat = str(row.get(cat_col) or "").strip() or None
            lvl = str(row.get(lvl_col) or "").strip() or None
            hits = by_key.get((cat, lvl), [])
            if not hits:
                unmatched.append(row.to_dict())
                continue
            tid = str(row[task_col])
            for el in hits:
                links.append((tid, el.speckle_object_id))

    else:
        # name_fuzzy / wbs_pattern not implemented deterministically yet.
        unmatched = df.head(5).to_dict(orient="records")

    return links, unmatched


def _guess_column(df: pd.DataFrame, mapping: list[dict[str, Any]], needles: list[str]) -> str | None:
    # First, check if any mapping entry's speckle_property matches one of the
    # needles — that's the column the user picked.
    for m in mapping:
        prop = (m.get("speckle_property") or "").lower()
        if any(n in prop for n in needles) and m.get("column") in df.columns:
            return m["column"]
    # Otherwise, header heuristics.
    for col in df.columns:
        c = col.lower()
        if any(n in c for n in needles):
            return col
    return None


@celery.task(name="app.tasks.resolve_rows.run", bind=True)
def run(self, job_id: str, schedule_id: str) -> dict:
    with SyncSessionLocal() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one()
        try:
            _update_job(session, job, state="running", progress=0.1, message="Loading mapping…")

            schedule = session.execute(
                select(ScheduleUpload).where(ScheduleUpload.id == schedule_id)
            ).scalar_one()
            proposal = session.execute(
                select(MappingProposal)
                .where(MappingProposal.schedule_id == schedule_id)
                .order_by(MappingProposal.created_at.desc())
                .limit(1)
            ).scalar_one()

            confirmed = proposal.confirmed or proposal.proposed
            mapping_entries = confirmed.get("mapping", [])
            join_strategy = confirmed.get("join_strategy", proposal.join_strategy)
            role_col = _role_to_column(mapping_entries)

            df = read_schedule(Path(schedule.storage_path))

            elements: list[ElementIndex] = list(
                session.execute(
                    select(ElementIndex).where(
                        ElementIndex.user_id == schedule.user_id,
                        ElementIndex.speckle_project_id == schedule.speckle_project_id,
                        ElementIndex.speckle_version_id == schedule.speckle_version_id,
                    )
                )
                .scalars()
                .all()
            )

            _update_job(session, job, progress=0.6, message=f"Resolving via {join_strategy}…")
            links, unmatched_samples = _resolve(
                df, role_col, join_strategy, elements, mapping_entries
            )

            session.execute(
                delete(ScheduleElementLink).where(
                    ScheduleElementLink.schedule_id == schedule.id
                )
            )
            for task_id, speckle_id in links:
                session.add(
                    ScheduleElementLink(
                        schedule_id=schedule.id,
                        task_id=task_id,
                        speckle_object_id=speckle_id,
                        source="deterministic",
                        confidence=1.0,
                    )
                )
            session.commit()

            unique_tasks = {tid for tid, _ in links}
            total_rows = int(len(df))
            result = {
                "schedule_id": schedule.id,
                "join_strategy": join_strategy,
                "total_rows": total_rows,
                "matched_rows": len(unique_tasks),
                "unmatched_rows": max(total_rows - len(unique_tasks), 0),
                "total_links": len(links),
                "unmatched_samples": [
                    {k: (str(v) if v is not None else None) for k, v in r.items()}
                    for r in unmatched_samples[:10]
                ],
            }
            _update_job(
                session,
                job,
                state="ready",
                progress=1.0,
                message=f"Matched {result['matched_rows']}/{total_rows} rows.",
                result=result,
            )
            return result
        except Exception as e:  # noqa: BLE001
            _update_job(
                session,
                job,
                state="failed",
                error=f"{type(e).__name__}: {e}\n{traceback.format_exc()[:4000]}",
                message="Resolution failed.",
            )
            raise
