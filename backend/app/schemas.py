"""Pydantic-схемы API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import TriggerType, ValidationStatus


# --- Аналитики ---


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
    # чем проверяли: версия шаблона и пользовательский промт (NULL — стандартный)
    template_version_id: int | None = None
    ai_prompt: str | None = None


# --- Настройки запуска проверки (диалог выбора шаблона и промта) ---


class ValidationOptions(BaseModel):
    """Настройки одного запуска проверки: шаблон + промт ИИ.

    Все поля опциональны — запуск без тела остаётся совместимым
    (активный шаблон, стандартный промт).
    """

    template_id: int | None = Field(default=None, description="Версия шаблона требований")
    ai_prompt: str | None = Field(
        default=None, max_length=32_000, description="Промт ИИ на этот запуск"
    )

    @field_validator("ai_prompt")
    @classmethod
    def prompt_not_blank(cls, value: str | None) -> str | None:
        # пустая строка = «стандартный промт», пробельная — ошибка ввода
        if value is not None and not value.strip():
            raise ValueError("Промт не может состоять из одних пробелов")
        return value


class ValidationBatchRequest(ValidationOptions):
    """Проверка набора выбранных документов (последовательно, в фоне)."""

    document_ids: list[int] = Field(min_length=1, max_length=200)
    force: bool = Field(default=False, description="Перевалидировать безусловно")


class TemplateOptionOut(BaseModel):
    """Шаблон в списке выбора диалога проверки."""

    id: int
    name: str
    description: str | None = None
    is_default: bool
    section_count: int


class ValidationConfigOut(BaseModel):
    """Конфиг диалога проверки: доступные шаблоны и стандартный промт ИИ."""

    templates: list[TemplateOptionOut]
    default_prompt: str


# --- Шаблон требований (UI-редактор) ---


class TemplateSection(BaseModel):
    """Раздел шаблона: уровень 1..3 задаёт вложенность, порядок — позиция в списке."""

    level: int = Field(ge=1, le=3)
    text: str = Field(min_length=1, max_length=255)
    required: bool = False
    aliases: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("text")
    @classmethod
    def text_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Название раздела не может быть пустым")
        return cleaned


class TemplateUpdate(BaseModel):
    """PUT /api/template: маркер названия + плоский список разделов.

    name/description и повторяемые блоки из UI не редактируются —
    переносятся из предыдущей версии (см. services.template_store).
    """

    title_marker: str = Field(default="", max_length=100)
    sections: list[TemplateSection] = Field(default_factory=list, max_length=200)


class TemplateOut(BaseModel):
    """Активная версия шаблона. id = номер версии."""

    id: int
    name: str
    description: str | None = None
    title_marker: str
    sections: list[TemplateSection]
    created_at: datetime


class TemplateVersionInfo(BaseModel):
    """Строка истории версий шаблона."""

    id: int
    name: str
    created_at: datetime
    is_active: bool
    section_count: int


# --- Заметки руководителя ---


class NoteUpdate(BaseModel):
    """ФТ-CR-18: заметка — произвольный Markdown, одна на документ."""

    content: str = Field(default="", max_length=100_000)


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    content: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
