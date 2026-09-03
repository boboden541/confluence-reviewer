"""Схемы организационной структуры: кластеры и команды."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ClusterCreate(BaseModel):
    """Создание кластера: минимум название."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    # hex-цвет из палитры UI; пусто — фронт подставит нейтральный
    color: str | None = Field(default=None, max_length=16)


class ClusterUpdate(BaseModel):
    """Редактирование кластера: те же поля, что при создании."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    color: str | None = Field(default=None, max_length=16)


class TeamBrief(BaseModel):
    """Команда в составе кластера (карточки и мини-схемы)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    analysts_count: int = 0


class ClusterOut(BaseModel):
    """Кластер с составом и счётчиками (карта кластеров, экран кластера)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    color: str | None = None
    created_at: datetime
    teams_count: int = 0
    analysts_count: int = 0
    documents_count: int = 0
    teams: list[TeamBrief] = []


class TeamCreate(BaseModel):
    """Создание команды внутри кластера."""

    cluster_id: int
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class TeamUpdate(BaseModel):
    """Редактирование команды; кластер не меняется (перенос команд не нужен)."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class AnalystBrief(BaseModel):
    """Аналитик в составе команды (карточки на экране команды)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str
    documents_count: int = 0
    domains: list[str] = []


class TeamOut(BaseModel):
    """Команда с составом; домены команды — уникальные домены участников."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    cluster_id: int
    cluster_name: str
    cluster_color: str | None = None
    name: str
    description: str | None = None
    created_at: datetime
    analysts: list[AnalystBrief] = []
    domains: list[str] = []


class TeamAnalystAdd(BaseModel):
    """Привязка аналитика к команде; домены None — оставить как есть,
    список — перезаписать (пустой — очистить)."""

    analyst_id: int
    domains: list[str] | None = Field(default=None, max_length=50)
