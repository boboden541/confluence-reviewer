"""Pydantic-схемы API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import TriggerType, ValidationStatus


# --- Аналитики ---


class AnalystCreate(BaseModel):
    """ФТ-CR-1: карточка минимум из ФИО и email."""

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


# --- Документы ---


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


class DocumentPage(BaseModel):
    """Постраничный ответ списка документов."""

    items: list[DocumentListItem]
    total: int
    page: int
    page_size: int


class DocumentOut(DocumentListItem):
    """Полный объект документа (для страницы отчёта)."""

    content_html: str
    sync_error: str | None = None


# --- Отчёты валидации ---


class ValidationReportOut(BaseModel):
    """Отчёт по двум проверкам: шаблон + ИИ (ФТ-CR-13, ФТ-CR-16)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    triggered_by: TriggerType
    created_at: datetime
    template_passed: bool
    template_findings: str
    ai_passed: bool | None = None
    ai_findings: str | None = None
    overall_passed: bool
    error_message: str | None = None
    comment_sent_at: datetime | None = None
