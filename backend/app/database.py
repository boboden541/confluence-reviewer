"""Подключение к БД и сессии SQLAlchemy."""

from __future__ import annotations

import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

logger = logging.getLogger("confluence_reviewer.database")

# Колонки, добавленные к существующим таблицам после развёртывания.
# create_all новые таблицы создаёт, но старые не изменяет — недостающие
# колонки добавляем ALTER'ами (идемпотентно, sqlite и postgres).
_ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "validation_reports": [
        ("template_version_id", "INTEGER REFERENCES template_versions(id) ON DELETE SET NULL"),
        ("ai_prompt", "TEXT"),
        ("ai_model_used", "VARCHAR(128)"),
        # Критерии ИИ-проверки, из которых собран промт прогона (JSON-список кодов)
        ("ai_criteria_codes", "TEXT"),
        # Хэш эффективного промта (override или собранного из критериев):
        # смена промта критерия меняет хэш → документ перевалидируется (ФТ-CR-14)
        ("ai_prompt_hash", "VARCHAR(64)"),
    ],
    # Контейнер-шаблон у версии (поддержка нескольких шаблонов); nullable —
    # существующие строки заполняет _migrate_template_containers
    "template_versions": [
        ("template_id", "INTEGER REFERENCES templates(id) ON DELETE CASCADE"),
    ],
    # Организационная структура: команда аналитика (NULL — «без команды») и
    # его домены (JSON-список строк, default '[]'). Без ON DELETE каскада —
    # при удалении команды usecase сначала отвязывает участников.
    "analysts": [
        ("team_id", "INTEGER REFERENCES teams(id)"),
        ("domains", "TEXT DEFAULT '[]'"),
        # куратор-лид из числа пользователей сервиса (NULL — не назначен)
        ("lead_user_id", "INTEGER REFERENCES users(id)"),
    ],
    # Персональные шаблоны и критерии: владелец (NULL — только до миграции,
    # заполняет seed_auth на God-пользователя)
    "templates": [
        ("owner_user_id", "INTEGER REFERENCES users(id)"),
    ],
    "ai_criteria": [
        ("owner_user_id", "INTEGER REFERENCES users(id)"),
    ],
    # Персональный доступ к ИИ: NULL — настройка «по умолчанию» (правит God),
    # у каждой пользователя — максимум одна своя строка
    "ai_connection_settings": [
        ("user_id", "INTEGER REFERENCES users(id)"),
    ],
}


def _migrate_added_columns() -> None:
    inspector = inspect(engine)
    for table, columns in _ADDED_COLUMNS.items():
        if not inspector.has_table(table):
            continue  # таблицу создаст create_all уже с новыми колонками
        existing = {col["name"] for col in inspector.get_columns(table)}
        with engine.begin() as conn:
            for name, ddl in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    logger.info("Миграция: добавлена колонка %s.%s", table, name)


# Колонки, ставшие nullable после развёртывания (семантика NULL — «проверка
# не запускалась»). SQLite не умеет ALTER COLUMN — тестовая БД там каждый раз
# создаётся заново уже по новой модели; для существующего postgres — DROP NOT NULL.
_NULLABLE_COLUMNS: dict[str, list[str]] = {
    "validation_reports": ["template_passed"],
}


def _migrate_nullable_columns() -> None:
    if engine.dialect.name != "postgresql":
        return
    inspector = inspect(engine)
    for table, columns in _NULLABLE_COLUMNS.items():
        if not inspector.has_table(table):
            continue  # таблицу создаст create_all уже с nullable-колонкой
        current = {col["name"]: col for col in inspector.get_columns(table)}
        with engine.begin() as conn:
            for name in columns:
                if name in current and not current[name]["nullable"]:
                    conn.execute(
                        text(f"ALTER TABLE {table} ALTER COLUMN {name} DROP NOT NULL")
                    )
                    logger.info("Миграция: колонка %s.%s теперь nullable", table, name)


# Шкала оценок руководителя: 1..5 → 1..10. Маркер применения — имя
# чек-констрейнта в БД (новое имя стоит — миграция уже прошла).
_OLD_SCORE_CHECK = "ck_criterion_ratings_score"
_NEW_SCORE_CHECK = "ck_criterion_ratings_score_1_10"


def _migrate_rating_scale() -> None:
    """Шкала оценок 1..5 → 1..10; существующие баллы удваиваются (3→6, 5→10).

    Однократно и идемпотентно: маркер — имя чек-констрейнта. Атомарно:
    postgres DDL транзакционен, всё в одном engine.begin() — падение между
    UPDATE и ADD откатывает и то и другое, повторного удвоения не будет.
    SQLite не умеет ALTER CONSTRAINT — тестовая БД создаётся заново уже
    по новой модели, поэтому здесь работает только postgres.
    """
    inspector = inspect(engine)
    if not inspector.has_table("criterion_ratings"):
        return  # таблицу создаст create_all уже с новой шкалой
    names = {c["name"] for c in inspector.get_check_constraints("criterion_ratings")}
    if _NEW_SCORE_CHECK in names:
        return  # новая шкала уже стоит (create_all или прошлый запуск)
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        if _OLD_SCORE_CHECK in names:
            conn.execute(
                text(f"ALTER TABLE criterion_ratings DROP CONSTRAINT {_OLD_SCORE_CHECK}")
            )
        conn.execute(text("UPDATE criterion_ratings SET score = score * 2"))
        conn.execute(
            text(
                f"ALTER TABLE criterion_ratings ADD CONSTRAINT {_NEW_SCORE_CHECK} "
                "CHECK (score BETWEEN 1 AND 10)"
            )
        )
    logger.info("Миграция: шкала оценок 1..5 → 1..10, существующие баллы удвоены")


def _migrate_template_containers() -> None:
    """Существующая цепочка версий (эпоха одного шаблона) → первый шаблон.

    Однократно и идемпотентно: срабатывает, только когда контейнеров ещё
    нет, а версии уже есть. Новый шаблон получает пометку «по умолчанию» —
    поведение для пользователей не меняется."""
    from sqlalchemy import func, insert, select, update

    from app.models import Template, TemplateVersion

    with engine.begin() as conn:
        if conn.execute(select(func.count()).select_from(Template)).scalar():
            return  # контейнеры уже есть — миграция не нужна
        if not conn.execute(select(func.count()).select_from(TemplateVersion)).scalar():
            return  # версий нет — первый шаблон создаст сид
        template_id = conn.execute(insert(Template).values(is_default=True)).inserted_primary_key[0]
        conn.execute(update(TemplateVersion).values(template_id=template_id))
        logger.info("Миграция: версии шаблона объединены в шаблон №%s", template_id)


class Base(DeclarativeBase):
    pass


settings = get_settings()

connect_args = {}
if settings.database_url.startswith("sqlite"):
    # Для тестов: один файл в памяти, общее соединение
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args=connect_args,
)

if settings.database_url.startswith("sqlite"):
    # SQLite lower()/LIKE сворачивают только ASCII — кириллица ломает поиск.
    # Переопределяем lower на unicode-aware (в postgres работает из коробки).
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _register_unicode_lower(dbapi_conn, _record):  # pragma: no cover - тестовая БД
        dbapi_conn.create_function(
            "lower", 1, lambda value: value.lower() if isinstance(value, str) else value
        )

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(retries: int = 15, delay: float = 2.0) -> None:
    """Создать таблицы; с ретраями — БД в docker может подниматься дольше приложения."""
    import time

    from app import models  # noqa: F401 — регистрация моделей до create_all

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            Base.metadata.create_all(bind=engine)
            _migrate_added_columns()
            _migrate_nullable_columns()
            _migrate_rating_scale()
            _migrate_template_containers()
            return
        except Exception as exc:  # pragma: no cover - зависит от окружения
            last_error = exc
            time.sleep(delay)
    raise RuntimeError(f"Не удалось подключиться к БД: {last_error}")
