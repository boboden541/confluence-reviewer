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

    # Первая версия шаблона требований — из файла, если в БД ещё нет
    from app.database import SessionLocal
    from app.services.template_store import seed_if_missing

    with SessionLocal() as db:
        if seed_if_missing(db) is not None:
            logger.info("Первая версия шаблона требований создана из файла")

    # ФТ-CR-5: регламентная автосинхронизация раз в N часов
    scheduler = None
    if settings.confluence_base_url:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        from app.services.tasks import start_sync

        scheduler = AsyncIOScheduler(timezone="UTC")
        scheduler.add_job(
            lambda: start_sync(None),
            trigger="interval",
            hours=max(settings.sync_interval_hours, 1),
            id="scheduled_sync",
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        logger.info(
            "Планировщик запущен: синхронизация каждые %s ч", settings.sync_interval_hours
        )
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


def create_app(settings=None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    # НФТ-CR-7: basic-auth на всё, кроме /api/health. Добавляется раньше CORS,
    # чтобы ошибки 401 тоже получали CORS-заголовки (middleware идёт позже — внешне).
    if settings.auth_enabled:
        from app.auth import BasicAuthMiddleware

        app.add_middleware(
            BasicAuthMiddleware,
            username=settings.app_username,
            password=settings.app_password,
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
    from app.routers.documents import router as documents_router
    from app.routers.health import router as health_router
    from app.routers.sync import router as sync_router
    from app.routers.templates import router as templates_router

    app.include_router(health_router)
    app.include_router(analysts_router)
    app.include_router(documents_router)
    app.include_router(sync_router)
    app.include_router(templates_router)

    return app


app = create_app()
