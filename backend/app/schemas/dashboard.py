"""Схемы главной страницы: очередь внимания и лента событий.

Секции очереди фиксированы и типизированы (type → иконка/цвет/маршрут на
фронте), items — универсальные «строки внимания» со ссылкой на объект.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DashboardItem(BaseModel):
    """Строка очереди внимания: заголовок, причина и ссылка на объект."""

    key: str = Field(description="Уникальный ключ строки (для React-ключей)")
    title: str
    subtitle: str = ""
    at: datetime | None = None
    document_id: int | None = None
    analyst_id: int | None = None
    template_id: int | None = None
    # маршрут настройки для секции справочников: templates|criteria|ai
    section: str | None = None


class DashboardSection(BaseModel):
    """Секция очереди внимания: тип, заголовок, полный счётчик и строки."""

    type: str = Field(
        description="failed|stale|ratings|no_team|references — маппится на иконку и цвет"
    )
    title: str
    total: int
    items: list[DashboardItem] = Field(default_factory=list, max_length=8)


class DashboardOut(BaseModel):
    sections: list[DashboardSection]


class FeedItem(BaseModel):
    """Событие ленты: тип, момент и полезная нагрузка исходного события."""

    type: str
    at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
