"""Глобальные настройки подключения ИИ (таблица ai_connection_settings).

Одна строка (id=1) перекрывает env по-полю: пустое поле строки или её
отсутствие = значение из окружения. api_key наружу отдаётся только маской
и нигде не логируется.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import AIConnectionSettings

PROTOCOLS = ("anthropic", "openai")


@dataclass(frozen=True, slots=True)
class AIConnection:
    """Эффективные параметры обращения к ИИ (после склейки строка+env)."""

    protocol: str
    base_url: str
    api_key: str
    model: str
    max_tokens: int
    timeout_seconds: float


def connection_from_settings(s: Settings) -> AIConnection:
    """Подключение из настроек окружения (загрузочный дефолт)."""
    return AIConnection(
        protocol=s.ai_protocol if s.ai_protocol in PROTOCOLS else "anthropic",
        base_url=normalize_base_url(s.ai_base_url),
        api_key=s.ai_api_key,
        model=s.ai_model,
        max_tokens=s.ai_max_tokens,
        timeout_seconds=s.ai_timeout_seconds,
    )


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


def normalize_base_url(value: str) -> str:
    """URL без пробелов и хвостовых слэшей (путь дополним при запросе)."""
    return value.strip().rstrip("/")
