"""Схемы аналитиков и заметок по ним."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


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


class AnalystNoteUpdate(BaseModel):
    """Заметка в профиле аналитика — произвольный Markdown, одна на аналитика."""

    content: str = Field(default="", max_length=100_000)


class AnalystNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analyst_id: int
    content: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
