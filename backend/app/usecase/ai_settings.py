"""Глобальные настройки подключения ИИ (таблица ai_connection_settings).

Одна строка (id=1) перекрывает env по-полю: пустое поле строки или её
отсутствие = значение из окружения. api_key наружу отдаётся только маской
и нигде не логируется.
"""

from __future__ import annotations

from sqlalchemy import select
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


def save_settings(
    db: Session, payload: AIConnectionUpdate, user_id: int | None = None
) -> AIConnectionSettings:
    """Сохранить настройки: личные пользователя (user_id) или «по умолчанию»
    (user_id=None, одна строка). api_key=None не трогает сохранённый токен,
    "" — очищает его. Применяется к следующим запускам проверки."""
    if user_id is None:
        row = repository.ai_settings.get_row(db)
    else:
        row = db.scalar(
            select(AIConnectionSettings).where(AIConnectionSettings.user_id == user_id)
        )
    if row is None:
        row = AIConnectionSettings(user_id=user_id)
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


def get_default_row(db: Session) -> AIConnectionSettings | None:
    """Настройка «по умолчанию» (user_id IS NULL) — правит God."""
    return repository.ai_settings.get_row(db)


def get_ai_connection(db: Session, user=None) -> AIConnection | None:
    """Эффективное подключение пользователя.

    Личная строка (заполненная целиком) приоритетна. Без неё: God и
    выключенная авторизация — настройка по умолчанию (строка без user_id
    поверх env); остальные — None: ИИ-проверки заблокированы, пока
    пользователь не настроит личный доступ.
    """
    env = connection_from_settings(get_settings())

    def _from_row(row) -> AIConnection:
        protocol = row.protocol if row.protocol in PROTOCOLS else env.protocol
        return AIConnection(
            protocol=protocol,
            base_url=normalize_base_url(row.base_url) if row.base_url else env.base_url,
            api_key=row.api_key or env.api_key,
            model=row.model or env.model,
            max_tokens=env.max_tokens,
            timeout_seconds=env.timeout_seconds,
        )

    personal = get_row_for_user(db, user)
    if personal is not None and personal.base_url and personal.api_key and personal.model:
        return _from_row(personal)

    is_god = user is not None and user.role.is_system
    if user is not None and not is_god:
        return None  # лид без личного доступа: ИИ-проверки заблокированы

    default = get_default_row(db)
    if default is not None:
        return _from_row(default)
    return env


def mask_api_key(value: str) -> str:
    """Маска токена для UI: открытым текстом не отдаём никогда."""
    value = value.strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "••••"
    return f"{value[:3]}…{value[-3:]}"

def get_row_for_user(db, user) -> AIConnectionSettings | None:
    """Личная строка настроек пользователя (без фолбэка на дефолт)."""
    if user is None:
        return None
    from sqlalchemy import select

    from app.models import AIConnectionSettings

    return db.scalar(
        select(AIConnectionSettings).where(AIConnectionSettings.user_id == user.id)
    )




def get_row_for_user(db, user) -> AIConnectionSettings | None:
    """Личная строка настроек пользователя (без фолбэка на дефолт)."""
    if user is None:
        return None
    from sqlalchemy import select

    from app.models import AIConnectionSettings

    return db.scalar(
        select(AIConnectionSettings).where(AIConnectionSettings.user_id == user.id)
    )


def ai_configured(db, user) -> bool:
    """Личный доступ заполнен целиком (URL + модель + токен) — без него
    ИИ-проверки пользователя заблокированы."""
    row = get_row_for_user(db, user)
    return bool(row and row.base_url and row.model and row.api_key)
