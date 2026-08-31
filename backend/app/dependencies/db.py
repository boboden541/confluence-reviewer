"""Зависимость сессии БД для роутеров."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from app.database import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI-зависимость: сессия с гарантированным закрытием."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
