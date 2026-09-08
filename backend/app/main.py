"""Точка входа FastAPI: Confluence Reviewer."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db
from app.dependencies import add_catch_all, install_auth, require_user

logger = logging.getLogger("confluence_reviewer")
logging.basicConfig(level=logging.INFO)


def _lifespan_for(settings):
    """Lifespan замкнут на настройки конкретного приложения (create_app может
    получить их аргументом — тесты), а не на глобальный get_settings()."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db()

        # Первичное наполнение: карточки аналитиков и первая версия шаблона
        # требований — одна сессия на все сиды
        from app.database import SessionLocal
        from app.usecase.auth import seed_auth
        from app.usecase.seed import seed_analysts
        from app.usecase.templates import seed_if_missing

        with SessionLocal() as db:
            # роли и God-пользователь — до сидов контента: он пишет владельца
            seed_auth(db, settings)

            if settings.seed_analysts:
                created = seed_analysts(db, settings.seed_analysts)
                if created:
                    logger.info("Первичное наполнение: создано карточек аналитиков — %d", created)

            if seed_if_missing(db) is not None:
                logger.info("Первая версия шаблона требований создана из файла")

        # ФТ-CR-5: регламентная автосинхронизация раз в N часов
        scheduler = None
        if settings.confluence_base_url:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler

            from app.usecase.tasks import start_sync

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

    return lifespan


def create_app(settings=None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=_lifespan_for(settings),
        # Авторизация Bearer-сессиями на всё, кроме /api/health и входов.
        # 401 генерируется внутри приложения, поэтому CORS-заголовки ставит
        # внешняя CORSMiddleware
        dependencies=[Depends(require_user)],
    )

    # Параметры авторизации в app.state + закрытые docs/catch-all (детали —
    # в dependencies.auth: глобальная зависимость туда не дотягивается)
    install_auth(app, settings)

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

    from app.api.ai_settings import router as ai_settings_router
    from app.api.analysts import router as analysts_router
    from app.api.auth import roles_router, router as auth_router, users_router
    from app.api.criteria import router as criteria_router
    from app.api.dashboard import router as dashboard_router
    from app.api.documents import router as documents_router
    from app.api.events import router as events_router
    from app.api.health import router as health_router
    from app.api.org import clusters_router, teams_router
    from app.api.sync import router as sync_router
    from app.api.templates import multi_router as templates_multi_router
    from app.api.templates import router as templates_router

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(roles_router)
    app.include_router(users_router)
    app.include_router(analysts_router)
    app.include_router(clusters_router)
    app.include_router(teams_router)
    app.include_router(criteria_router)
    app.include_router(documents_router)
    app.include_router(events_router)
    app.include_router(sync_router)
    app.include_router(dashboard_router)
    app.include_router(templates_router)
    app.include_router(templates_multi_router)
    app.include_router(ai_settings_router)

    # последним: неизвестные пути без учётки — 401, а не 404
    add_catch_all(app)

    return app


app = create_app()
