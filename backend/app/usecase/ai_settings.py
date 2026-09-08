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


def save_settings(
    db: Session, payload: AIConnectionUpdate, user_id: int | None = None
) -> AIConnectionSettings:
    """Сохранить настройки: личные пользователя (user_id) или «по умолчанию»
    (user_id=None, одна строка). api_key=None не трогает сохранённый токен,
    "" — очищает его. Применяется к следующим запускам проверки."""
    if user_id is None:
        row = get_default_row(db)
    else:
        row = db.scalar(
            select(AIConnectionSettings).where(AIConnectionSettings.user_id == user_id)
        )
    if row is None:
        row = AIConnectionSettings(user_id=user_id)
        db.add(row)
    row.protocol = payload.protocol

    if user_id is None:
        # «по умолчанию» (God): легаси-семантика — пусто = значение из env;
        # пустой api_key = очистить сохранённый токен
        row.base_url = normalize_base_url(payload.base_url)
        row.model = payload.model
        if payload.api_key is not None:
            row.api_key = payload.api_key.strip()
    else:
        # личная строка сохраняется ПОЛНОЙ: пустые поля наследуются из
        # настройки по умолчанию / env — иначе guard навсегда держал бы
        # проверки заблокированными из-за визуально заполненного поля
        default = get_default_row(db)
        env = connection_from_settings(get_settings())

        def _resolve(value: str, fallback_row, env_value: str) -> str:
            value = value.strip()
            if value:
                return normalize_base_url(value) if value.startswith("http") else value
            return (getattr(fallback_row, env_value, "") if fallback_row else "") or env_value

        row.base_url = _resolve(payload.base_url, default, "base_url") or env.base_url
        row.model = _resolve(payload.model, default, "model") or env.model
        if payload.api_key is not None and payload.api_key.strip():
            row.api_key = payload.api_key.strip()
        elif not row.api_key:
            row.api_key = (default.api_key if default else "") or env.api_key
    db.commit()
    db.refresh(row)
    return row


def get_default_row(db: Session) -> AIConnectionSettings | None:
    """Настройка «по умолчанию»: строка без user_id (не pk id=1 — личные
    строки пользователей живут в той же таблице)."""
    from sqlalchemy import select

    return db.scalar(
        select(AIConnectionSettings).where(AIConnectionSettings.user_id.is_(None)).limit(1)
    )


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



def ai_configured(db, user) -> bool:
    """Личный доступ заполнен целиком (URL + модель + токен) — без него
    ИИ-проверки пользователя заблокированы."""
    row = get_row_for_user(db, user)
    return bool(row and row.base_url and row.model and row.api_key)
