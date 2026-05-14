from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth.speckle_oauth import router as speckle_oauth_router
from .config import settings
from .db import init_db
from .routes.jobs import router as jobs_router
from .routes.me import router as me_router
from .routes.schedules import router as schedules_router
from .routes.speckle import router as speckle_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield


app = FastAPI(title="BIM AI Backend — Speckle M1", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_base_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(speckle_oauth_router)
app.include_router(me_router)
app.include_router(speckle_router)
app.include_router(schedules_router)
app.include_router(jobs_router)
