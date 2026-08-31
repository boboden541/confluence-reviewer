"""Схемы шаблона требований (UI-редактор)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


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
    """PUT /api/template (legacy): маркер названия + плоский список разделов.

    name/description и повторяемые блоки из UI не редактируются —
    переносятся из предыдущей версии (см. services.template_store).
    """

    title_marker: str = Field(default="", max_length=100)
    sections: list[TemplateSection] = Field(default_factory=list, max_length=200)


class TemplateSave(BaseModel):
    """POST/PUT /api/templates: название, описание, маркер и структура.

    Название видно в диалоге проверки; каждое сохранение создаёт новую
    версию — история помнит, как шаблон назывался в момент проверки."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    title_marker: str = Field(default="", max_length=100)
    sections: list[TemplateSection] = Field(default_factory=list, max_length=200)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Название шаблона не может быть пустым")
        return cleaned

    @field_validator("description")
    @classmethod
    def description_clean(cls, value: str | None) -> str | None:
        return value.strip() if value else value


class TemplateCardOut(BaseModel):
    """Карточка шаблона в списке раздела (и архивный блок)."""

    id: int
    name: str
    description: str | None = None
    is_default: bool
    is_archived: bool
    # Активная версия: её id уходит в проверку как template_id
    active_version_id: int | None = None
    active_version_created_at: datetime | None = None
    section_count: int = 0
    title_marker: str = ""


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
