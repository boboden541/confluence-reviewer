"""Подключение к БД и сессии SQLAlchemy."""

from __future__ import annotations

import logging
from collections.abc import Generator

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


def get_db() -> Generator[Session, None, None]:
    """FastAPI-зависимость: сессия с гарантированным закрытием."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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
            return
        except Exception as exc:  # pragma: no cover - зависит от окружения
            last_error = exc
            time.sleep(delay)
    raise RuntimeError(f"Не удалось подключиться к БД: {last_error}")
