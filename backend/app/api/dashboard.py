"""Главная страница: очередь внимания и лента событий (ФТ главной).

Очередь — агрегат по существующим данным (статусы, отчёты, оценки,
справочники); лента — журнал последних событий фоновых задач.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas import DashboardOut, FeedItem
from app.usecase import dashboard as dashboard_uc
from app.usecase import tasks

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardOut)
def get_dashboard(db: Session = Depends(get_db)):
    """Очередь внимания: что требует реакции руководителя прямо сейчас."""
    return dashboard_uc.get_dashboard(db)


@router.get("/feed", response_model=list[FeedItem])
def get_feed(limit: int = Query(default=30, ge=1, le=100)):
    """Последние события фоновых задач (свежие сверху) — для живой ленты."""
    return [
        FeedItem(type=event["type"], at=event["at"], payload={
            key: value for key, value in event.items() if key not in ("type", "at")
        })
        for event in tasks.recent_events(limit)
    ]
