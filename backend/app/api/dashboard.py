"""Главная страница: очередь внимания и лента событий (ФТ главной).

Очередь — агрегат по существующим данным (статусы, отчёты, оценки,
справочники); лента — журнал последних событий фоновых задач.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_user
from app.dependencies.auth import resolve_actor
from app.schemas import DashboardOut, FeedItem
from app.models import User
from app.usecase import dashboard as dashboard_uc
from app.usecase import tasks

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardOut)
def get_dashboard(db: Session = Depends(get_db), user: User | None = Depends(require_user)):
    """Очередь внимания: что требует реакции руководителя прямо сейчас."""
    from app.dependencies.auth import resolve_actor

    return dashboard_uc.get_dashboard(db, resolve_actor(db, user))


@router.get("/feed", response_model=list[FeedItem])
def get_feed(
    limit: int = Query(default=30, ge=1, le=100),
    actor_id: int | None = Query(default=None),
):
    """Последние события (свежие сверху); actor_id — только моя активность."""
    events = tasks.recent_events(limit * 3 if actor_id else limit)
    if actor_id is not None:
        events = [e for e in events if e.get("actor_id") == actor_id][:limit]
    return [
        FeedItem(type=event["type"], at=event["at"], payload={
            key: value for key, value in event.items() if key not in ("type", "at")
        })
        for event in events
    ]
