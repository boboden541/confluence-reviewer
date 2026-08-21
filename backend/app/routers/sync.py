"""Ручной запуск синхронизации и статус фоновой задачи (ФТ-CR-6)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.services import tasks

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.post("/all", status_code=status.HTTP_202_ACCEPTED)
def trigger_sync_all():
    started, message = tasks.start_sync(None)
    if not started:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return {"status": "started", "message": message}


@router.get("/status")
def sync_status():
    return tasks.sync_status()
