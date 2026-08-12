"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import init_db
from .jobs import get_job_manager
from .routes import ROUTERS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
log = logging.getLogger("ifcsched")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    init_db()
    log.info("data dir: %s", settings.data_dir)
    log.info("config dir: %s", settings.config_dir)
    log.info("LLM layer: %s", "enabled" if settings.llm_enabled else "disabled")
    yield
    get_job_manager().shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="IFC → Construction Schedule Generator",
        version="0.1.0",
        description=(
            "Upload an IFC model, profile it, pick a schedule level of detail, "
            "and generate a CPM-calculated construction programme."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in ROUTERS:
        app.include_router(router)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "llm_enabled": settings.llm_enabled}

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal error", "error": str(exc)[:400]},
        )

    return app


app = create_app()
