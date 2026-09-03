"""Слой доступа к данным: выборки SQLAlchemy по доменам.

Правила слоя: repository возвращает ORM-объекты/значения и не содержит
бизнес-логики; запись (add/commit) остаётся за usecase — сюда переносится
только чтение. Импортирует app.database и app.models.

Подмодули импортируются фасадом: обращение `repository.templates.…` из
usecase работает без отдельного import подмодуля.
"""

from app.repository import (
    ai_settings,
    analysts,
    criteria,
    documents,
    org,
    ratings,
    reports,
    templates,
)

__all__ = [
    "ai_settings",
    "analysts",
    "criteria",
    "documents",
    "org",
    "ratings",
    "reports",
    "templates",
]
