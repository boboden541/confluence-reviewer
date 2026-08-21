"""Точка входа FastAPI: Confluence Reviewer."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db

logger = logging.getLogger("confluence_reviewer")
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db()
    if settings.seed_analysts:
        from app.seed import seed_analysts

        created = seed_analysts(settings.seed_analysts)
        if created:
            logger.info("Первичное наполнение: создано карточек аналитиков — %d", created)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    # Для локальной разработки frontend (vite) ходит на backend напрямую;
    # в docker-стеке запросы идут через nginx same-origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from app.routers.analysts import router as analysts_router
    from app.routers.health import router as health_router

    app.include_router(health_router)
    app.include_router(analysts_router)

    return app


app = create_app()
