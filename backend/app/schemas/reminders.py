"""Схемы напоминаний: создание и карточка."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ReminderCreate(BaseModel):
    analyst_id: int
    document_id: int | None = None
    text: str = Field(min_length=1, max_length=1000)
    remind_at: datetime | None = None


class ReminderOut(BaseModel):
    id: int
    analyst_id: int
    analyst_name: str
    document_id: int | None = None
    document_title: str | None = None
    text: str
    remind_at: datetime | None = None
    done_at: datetime | None = None
    created_at: datetime
    status: str  # "open" | "done"
