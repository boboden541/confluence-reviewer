"""Глобальные настройки подключения ИИ (таблица ai_connection_settings).

Одна строка (id=1) перекрывает env по-полю: пустое поле строки или её
отсутствие = значение из окружения. api_key наружу отдаётся только маской
и нигде не логируется.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import repository
from app.clients.ai_validator import (
    PROTOCOLS,
    AIConnection,
    connection_from_settings,
    normalize_base_url,
)
from app.config import get_settings
from app.models import AIConnectionSettings
from app.schemas import AIConnectionUpdate
from app.utils import now_utc


def get_row(db: Session) -> AIConnectionSettings | None:
    """Сохранённая строка настроек (id=1) или None — поля пустые (= env)."""
    return repository.ai_settings.get_row(db)


def save_settings(db: Session, payload: AIConnectionUpdate) -> AIConnectionSettings:
    """Сохранить настройки (одна строка id=1). Пустое поле = значение из env.

    api_key=None не трогает сохранённый токен, "" — очищает его.
    Применяется к следующим запускам проверки (без перезапуска сервиса).
    """
    row = repository.ai_settings.get_row(db)
    if row is None:
        row = AIConnectionSettings(id=1)
        db.add(row)
    row.protocol = payload.protocol
    row.base_url = normalize_base_url(payload.base_url)
    row.model = payload.model
    if payload.api_key is not None:
        row.api_key = payload.api_key.strip()
    row.updated_at = now_utc()
    db.commit()
    db.refresh(row)
    return row


def get_ai_connection(db: Session) -> AIConnection:
    """Эффективное подключение: строка id=1 поверх env по-полю.

    Вызывается на каждый запуск валидации — сохранённые настройки
    применяются к следующей проверке без перезапуска сервиса.
    """
    env = connection_from_settings(get_settings())
    row = repository.ai_settings.get_row(db)
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
