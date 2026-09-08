"""Схемы аналитиков и заметок по ним."""

from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class AnalystCreate(BaseModel):
    """ФТ-CR-1: карточка минимум из ФИО и email."""

    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    confluence_username: str | None = Field(default=None, max_length=255)


class AnalystUpdate(BaseModel):
    """Редактирование карточки аналитика: те же поля, что при создании."""

    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    confluence_username: str | None = Field(default=None, max_length=255)


class AnalystOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: EmailStr
    confluence_username: str | None
    created_at: datetime
    documents_count: int = 0
    last_synced_at: datetime | None = None
    sync_error: str | None = None
    # организационная структура: NULL — «без команды»; домены — свободные теги
    team_id: int | None = None
    team_name: str | None = None
    cluster_id: int | None = None
    cluster_name: str | None = None
    domains: list[str] = []
    # куратор-лид (пользователь сервиса)
    lead_user_id: int | None = None
    lead_name: str | None = None

    @field_validator("domains", mode="before")
    @classmethod
    def _parse_domains_json(cls, value):
        """В ORM домены лежат JSON-строкой — парсим при валидации."""
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                return []
        return value


class AnalystNoteUpdate(BaseModel):
    """Заметка в профиле аналитика — произвольный Markdown, одна на аналитика."""

    content: str = Field(default="", max_length=100_000)


class AnalystDomainsUpdate(BaseModel):
    """Домены аналитика — свободные теги; дедупликация без учёта регистра."""

    domains: list[str] = Field(default_factory=list, max_length=50)


class AnalystNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analyst_id: int
    content: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AnalystLeadUpdate(BaseModel):
    """Назначение лида аналитику: id пользователя с ролью lead или null."""

    user_id: int | None = None
