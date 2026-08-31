"""Схемы отчётов валидации и настроек запуска проверки."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import TriggerType


class ValidationReportOut(BaseModel):
    """Отчёт по двум проверкам: шаблон + ИИ (ФТ-CR-13, ФТ-CR-16)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    triggered_by: TriggerType
    created_at: datetime
    # NULL — проверка шаблона не запускалась (выбор критериев в диалоге проверки)
    template_passed: bool | None = None
    template_findings: str
    ai_passed: bool | None = None
    ai_findings: str | None = None
    overall_passed: bool
    error_message: str | None = None
    comment_sent_at: datetime | None = None
    # чем проверяли: версия шаблона и пользовательский промт (NULL — стандартный)
    template_version_id: int | None = None
    ai_prompt: str | None = None
    # какой моделью ИИ проверяли (NULL — старые отчёты)
    ai_model_used: str | None = None
    # коды критериев, из которых собран промт ИИ прогона (JSON; NULL — старые отчёты)
    ai_criteria_codes: str | None = None


# --- Настройки запуска проверки (диалог выбора критериев, шаблона и промта) ---

# Критерии проверки: структура по шаблону / содержимое (ИИ)
CheckName = Literal["template", "ai"]


class ValidationOptions(BaseModel):
    """Настройки одного запуска проверки: критерии + шаблон + промт ИИ.

    Все поля опциональны — запуск без тела остаётся совместимым
    (оба критерия, активный шаблон, стандартный промт).
    """

    checks: list[CheckName] | None = Field(
        default=None, description="Что проверить на этом запуске: template / ai; None — оба"
    )
    template_id: int | None = Field(
        default=None, description="Версия шаблона требований (используется при checks template)"
    )
    ai_prompt: str | None = Field(
        default=None, max_length=32_000, description="Промт ИИ на этот запуск (override)"
    )
    # Критерии ИИ-проверки этого запуска (id); None — все активные.
    # Используется при checks ai; промт без замка собирается из них
    criterion_ids: list[int] | None = Field(
        default=None, description="Критерии ИИ-проверки запуска; None — все активные"
    )

    @field_validator("checks")
    @classmethod
    def checks_present(cls, value: list[CheckName] | None) -> list[CheckName] | None:
        # пустой список = ничего не выбрано; дубликаты схлопываем, порядок сохраняем
        if value is not None:
            unique = list(dict.fromkeys(value))
            if not unique:
                raise ValueError("Выберите хотя бы один критерий: template или ai")
            return unique
        return value

    @field_validator("ai_prompt")
    @classmethod
    def prompt_not_blank(cls, value: str | None) -> str | None:
        # пустая строка = «стандартный промт», пробельная — ошибка ввода
        if value is not None and not value.strip():
            raise ValueError("Промт не может состоять из одних пробелов")
        return value

    @field_validator("criterion_ids")
    @classmethod
    def criteria_present(cls, value: list[int] | None) -> list[int] | None:
        # пустой список = ни одного критерия: проверка наполнения бессмысленна
        if value is not None and not value:
            raise ValueError("Выберите хотя бы один критерий ИИ-проверки")
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


class CriterionOptionOut(BaseModel):
    """Активный критерий ИИ-проверки в конфиге диалога: галочка + блок промта."""

    id: int
    code: str
    name: str
    prompt: str


class ValidationConfigOut(BaseModel):
    """Конфиг диалога проверки: шаблоны, ИИ-критерии и части собранного промта.

    Превью промта фронт собирает как prompt_head + блоки критериев + prompt_tail
    (живое обновление по галочкам) — та же схема, что в usecase.criteria.
    """

    templates: list[TemplateOptionOut]
    default_prompt: str
    criteria: list[CriterionOptionOut] = Field(default_factory=list)
    prompt_head: str = ""
    prompt_tail: str = ""
