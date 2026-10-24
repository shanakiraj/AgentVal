"""FastAPI application entrypoint: ``uvicorn agentval.api.main:app``."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agentval import __version__
from agentval.api.routes import datasets, evals
from agentval.config import get_settings
from agentval.db import init_db

log = logging.getLogger("agentval")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    settings = get_settings()
    task = None
    if settings.seed_on_startup:
        from agentval.service import seed_sample

        task = asyncio.create_task(seed_sample())
        task.add_done_callback(lambda t: log.info("Sample data seeded: %s", t.result() if not t.exception() else t.exception()))
    yield
    if task and not task.done():
        task.cancel()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AgentVal API", version=__version__, lifespan=lifespan,
                  description="Agent Validation & Evaluation Studio - evaluation engine API")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                       allow_methods=["*"], allow_headers=["*"])
    app.include_router(datasets.router)
    app.include_router(evals.router)

    @app.get("/health", tags=["meta"])
    def health():
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
