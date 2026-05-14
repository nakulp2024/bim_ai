"""Sync DB session used by Celery workers (asyncpg is async-only)."""
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

sync_engine = create_engine(settings.database_url_sync, future=True)
SyncSessionLocal = sessionmaker(sync_engine, expire_on_commit=False, class_=Session)
