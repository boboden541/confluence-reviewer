"""API глобальных настроек подключения ИИ: просмотр, сохранение, тест связи.

Токен наружу отдаётся только маской; ошибка «Проверить подключение» —
не ошибка API (HTTP 200 с ok=false), чтобы фронтенд показал её в форме.
"""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.dependencies import get_db
from app.models import AIConnectionSettings
from app.schemas import (
    AIConnectionOut,
    AIConnectionTestRequest,
    AIConnectionTestResult,
    AIConnectionUpdate,
    AIEnvInfo,
)
from app.clients.ai_validator import AIValidationError, AIValidator
from app.services.ai_settings import (
    get_ai_connection,
    mask_api_key,
    normalize_base_url,
)
from app.utils import now_utc

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
def get_settings_row(db: Session = Depends(get_db)):
    """Сохранённые настройки + дефолты env. Строки нет — поля пустые (= env)."""
    return _to_out(db.get(AIConnectionSettings, 1))


@router.put("", response_model=AIConnectionOut)
def save_settings(payload: AIConnectionUpdate, db: Session = Depends(get_db)):
    """Сохранить настройки (одна строка id=1). Пустое поле = значение из env.

    api_key=None не трогает сохранённый токен, "" — очищает его.
    Применяется к следующим запускам проверки (без перезапуска сервиса).
    """
    row = db.get(AIConnectionSettings, 1)
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
    return _to_out(row)


@router.post("/test", response_model=AIConnectionTestResult)
def test_connection(payload: AIConnectionTestRequest, db: Session = Depends(get_db)):
    """Минимальный живой запрос с текущими значениями формы (до сохранения).

    Эффективные значения: форма → сохранённое → env. Сбой подключения —
    ок, а не исключение: пользователь видит сообщение в форме настроек.
    """
    saved = get_ai_connection(db)
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
