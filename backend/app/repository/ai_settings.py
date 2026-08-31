"""Выборка глобальных настроек подключения ИИ."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AIConnectionSettings


def get_row(db: Session) -> AIConnectionSettings | None:
    """Единственная строка настроек (id=1) или None."""
    return db.get(AIConnectionSettings, 1)
