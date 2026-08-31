"""Схемы документов и заметок руководителя по документам."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import ValidationStatus


class DocumentListItem(BaseModel):
    """Строка списка документов аналитика (ФТ-CR-7)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    confluence_page_id: str
    title: str
    url: str
    created_in_confluence_at: datetime | None
    last_modified_in_confluence_at: datetime | None
    validation_status: ValidationStatus
    last_validated_at: datetime | None
    # Есть ли у документа заметка руководителя (ФТ-CR-18) — видно в списке
    has_note: bool = False
    # Релевантность 0..1 — только в ответе семантического поиска
    score: float | None = None


class DocumentPage(BaseModel):
    """Постраничный ответ списка документов."""

    items: list[DocumentListItem]
    total: int
    page: int
    page_size: int


class SearchHit(BaseModel):
    """Результат глобального поиска по документам (строка поиска в шапке)."""

    id: int
    title: str
    validation_status: ValidationStatus
    analyst_id: int
    analyst_name: str


class DocumentOut(DocumentListItem):
    """Полный объект документа (для страницы отчёта)."""

    content_html: str
    sync_error: str | None = None
    # для кнопки «Назад» и хлебных крошек при прямом открытии страницы документа
    analyst_id: int
    # автор документа: сразу видно, чью страницу открыли (не из ORM — заполняет роутер)
    analyst_name: str = ""
    analyst_email: str | None = None


class NoteUpdate(BaseModel):
    """ФТ-CR-18: заметка — произвольный Markdown, одна на документ."""

    content: str = Field(default="", max_length=100_000)


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    content: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
