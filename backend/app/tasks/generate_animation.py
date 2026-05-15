"""Placeholder generate_animation task; real implementation lands in M4."""
from __future__ import annotations

from ..celery_app import celery


@celery.task(name="app.tasks.generate_animation.run", bind=True)
def run(self, job_id: str, schedule_id: str) -> dict:
    raise NotImplementedError("generate_animation lands in M4")
