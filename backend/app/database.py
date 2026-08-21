"""Подключение к БД и сессии SQLAlchemy."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


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
            return
        except Exception as exc:  # pragma: no cover - зависит от окружения
            last_error = exc
            time.sleep(delay)
    raise RuntimeError(f"Не удалось подключиться к БД: {last_error}")
