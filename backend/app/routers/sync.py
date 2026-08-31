"""Ручной запуск синхронизации и статус фоновой задачи (ФТ-CR-6)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.usecase import tasks

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.post("/all", status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync_all():
    # async def: эндпоинт исполняется в event loop, откуда можно создать фоновую задачу
    started, message = tasks.start_sync(None)
    if not started:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return {"status": "started", "message": message}


@router.get("/status")
def sync_status():
    return tasks.sync_status()


@router.get("/bulk-validation")
def bulk_validation_status():
    """Прогресс массовой проверки документов аналитика (для UI-поллинга)."""
    return tasks.bulk_status()
