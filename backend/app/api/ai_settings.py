"""API глобальных настроек подключения ИИ: просмотр, сохранение, тест связи.

Токен наружу отдаётся только маской; ошибка «Проверить подключение» —
не ошибка API (HTTP 200 с ok=false), чтобы фронтенд показал её в форме.
"""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.dependencies import get_db, require_user
from app.dependencies.auth import resolve_actor, require_permission
from app.models import AIConnectionSettings, User
from app.schemas import (
    AIConnectionOut,
    AIConnectionTestRequest,
    AIConnectionTestResult,
    AIConnectionUpdate,
    AIEnvInfo,
)
from app.clients.ai_validator import AIValidationError, AIValidator, normalize_base_url
from app.usecase.ai_settings import (
    get_ai_connection,
    get_default_row,
    get_row_for_user,
    mask_api_key,
    save_settings,
)

router = APIRouter(prefix="/api/ai-settings", tags=["ai-settings"])


def _to_out(row: AIConnectionSettings | None) -> AIConnectionOut:
    env = get_settings()
    return AIConnectionOut(
        protocol=row.protocol if row is not None else env.ai_protocol,
        base_url=row.base_url if row is not None else "",
        model=row.model if row is not None else "",
        api_key_masked=mask_api_key(row.api_key) if row is not None else "",
        updated_at=row.updated_at if row is not None else None,
        env=AIEnvInfo(
            protocol=env.ai_protocol,
            base_url=env.ai_base_url,
            model=env.ai_model,
            api_key_set=bool(env.ai_api_key),
        ),
    )


@router.get("", response_model=AIConnectionOut)
def get_settings_row(
    db: Session = Depends(get_db), user: User | None = Depends(require_user)
):
    """Мои сохранённые настройки (персональные). Строки нет — поля пустые."""
    actor = resolve_actor(db, user)
    return _to_out(get_row_for_user(db, actor))


@router.put("", response_model=AIConnectionOut)
def save_settings_row(
    payload: AIConnectionUpdate,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    """Сохранить мой личный доступ к ИИ (одна строка на пользователя).

    api_key=None не трогает сохранённый токен, "" — очищает его.
    Применяется к моим следующим запускам проверки (без перезапуска).
    """
    actor = resolve_actor(db, user)
    return _to_out(save_settings(db, payload, user_id=actor.id))


@router.get("/default", response_model=AIConnectionOut)
def get_default_settings(
    db: Session = Depends(get_db),
    _: User | None = Depends(require_permission("ai.default")),
):
    """Настройка «по умолчанию» (только God): применяется к тем, кто не
    настроил своё; сейчас её роль играет .env."""
    return _to_out(get_default_row(db))


@router.put("/default", response_model=AIConnectionOut)
def save_default_settings(
    payload: AIConnectionUpdate,
    db: Session = Depends(get_db),
    _: User | None = Depends(require_permission("ai.default")),
):
    """Сохранить настройку «по умолчанию» (только God)."""
    return _to_out(save_settings(db, payload, user_id=None))


@router.post("/test", response_model=AIConnectionTestResult)
def test_connection(
    payload: AIConnectionTestRequest,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    """Минимальный живой запрос с текущими значениями формы (до сохранения).

    Эффективные значения: форма → сохранённое → env. Сбой подключения —
    ок, а не исключение: пользователь видит сообщение в форме настроек.
    """
    saved = get_ai_connection(db, user)
    conn = replace(
        saved,
        protocol=payload.protocol,
        base_url=normalize_base_url(payload.base_url) or saved.base_url,
        api_key=payload.api_key.strip() or saved.api_key,
        model=payload.model.strip() or saved.model,
    )
    try:
        message = AIValidator(connection=conn).ping()
        return AIConnectionTestResult(ok=True, message=message)
    except AIValidationError as exc:
        return AIConnectionTestResult(ok=False, message=str(exc))
