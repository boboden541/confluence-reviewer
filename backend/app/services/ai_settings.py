"""Глобальные настройки подключения ИИ (таблица ai_connection_settings).

Одна строка (id=1) перекрывает env по-полю: пустое поле строки или её
отсутствие = значение из окружения. api_key наружу отдаётся только маской
и нигде не логируется.

Пока модуль живёт в services (перенос в usecase — отдельным шагом):
параметры подключения (AIConnection, connection_from_settings, PROTOCOLS,
normalize_base_url) уже переехали в clients.ai_validator и реэкспортируются
сюда для сохранения контракта импортов.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.clients.ai_validator import (
    PROTOCOLS,
    AIConnection,
    connection_from_settings,
    normalize_base_url,
)
from app.config import get_settings
from app.models import AIConnectionSettings

__all__ = [
    "PROTOCOLS",
    "AIConnection",
    "connection_from_settings",
    "get_ai_connection",
    "mask_api_key",
    "normalize_base_url",
]


def get_ai_connection(db: Session) -> AIConnection:
    """Эффективное подключение: строка id=1 поверх env по-полю.

    Вызывается на каждый запуск валидации — сохранённые настройки
    применяются к следующей проверке без перезапуска сервиса.
    """
    env = connection_from_settings(get_settings())
    row = db.get(AIConnectionSettings, 1)
    if row is None:
        return env
    protocol = row.protocol if row.protocol in PROTOCOLS else env.protocol
    return AIConnection(
        protocol=protocol,
        base_url=normalize_base_url(row.base_url) if row.base_url else env.base_url,
        api_key=row.api_key or env.api_key,
        model=row.model or env.model,
        max_tokens=env.max_tokens,
        timeout_seconds=env.timeout_seconds,
    )


def mask_api_key(value: str) -> str:
    """Маска токена для UI: открытым текстом не отдаём никогда."""
    value = value.strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "••••"
    return f"{value[:3]}…{value[-3:]}"
