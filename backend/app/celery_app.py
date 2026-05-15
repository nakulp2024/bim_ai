from celery import Celery

from .config import settings

celery = Celery(
    "bim_ai",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.map_columns",
        "app.tasks.resolve_rows",
        "app.tasks.generate_animation",
    ],
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
