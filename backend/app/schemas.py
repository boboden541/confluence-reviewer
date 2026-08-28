"""Pydantic-схемы API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

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
    (живое обновление по галочкам) — та же схема, что в services.criteria.
    """

    templates: list[TemplateOptionOut]
    default_prompt: str
    criteria: list[CriterionOptionOut] = Field(default_factory=list)
    prompt_head: str = ""
    prompt_tail: str = ""


# --- Справочник ИИ-критериев (раздел настроек) ---


class AiCriterionCreate(BaseModel):
    """Новый критерий: название + промт. Код сгенерируется из названия."""

    name: str = Field(min_length=1, max_length=255)
    prompt: str = Field(min_length=10, max_length=32_000)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Название критерия не может быть пустым")
        return cleaned

    @field_validator("prompt")
    @classmethod
    def prompt_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Промт критерия не может быть пустым")
        return cleaned


class AiCriterionUpdate(BaseModel):
    """Редактирование критерия. Код не меняется; переименование увидят и
    прошлые оценки в статистике — предупреждение в UI."""

    name: str = Field(min_length=1, max_length=255)
    prompt: str = Field(min_length=10, max_length=32_000)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Название критерия не может быть пустым")
        return cleaned

    @field_validator("prompt")
    @classmethod
    def prompt_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Промт критерия не может быть пустым")
        return cleaned


class AiCriterionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    prompt: str
    is_archived: bool
    created_at: datetime
    updated_at: datetime


# --- Настройки подключения ИИ (глобальные) ---


class AIEnvInfo(BaseModel):
    """Загрузочные дефолты из окружения — подсказки для полей UI."""

    protocol: str
    base_url: str
    model: str
    api_key_set: bool


class AIConnectionOut(BaseModel):
    """Сохранённые настройки подключения ИИ + дефолты env.

    Сохранённые поля отдаются как есть ("" = берётся из env); токен —
    только маской, открытым текстом не возвращается никогда.
    """

    protocol: str
    base_url: str
    model: str
    api_key_masked: str
    updated_at: datetime | None = None
    env: AIEnvInfo


class AIConnectionUpdate(BaseModel):
    """PUT /api/ai-settings. api_key: None — не менять, "" — очистить
    (fallback на env), строка — новое значение."""

    protocol: str
    base_url: str = Field(default="", max_length=512)
    model: str = Field(default="", max_length=128)
    api_key: str | None = Field(default=None, max_length=4096)

    @field_validator("protocol")
    @classmethod
    def protocol_known(cls, value: str) -> str:
        if value not in ("anthropic", "openai"):
            raise ValueError("Протокол должен быть anthropic или openai")
        return value

    @field_validator("base_url")
    @classmethod
    def base_url_http(cls, value: str) -> str:
        # пустое значение допустимо (= из env), непустое — только http(s)
        cleaned = value.strip()
        if cleaned and not cleaned.startswith(("http://", "https://")):
            raise ValueError("Базовый URL должен начинаться с http:// или https://")
        return cleaned.rstrip("/")

    @field_validator("model")
    @classmethod
    def model_not_blank(cls, value: str) -> str:
        # пустое значение допустимо (= из env), пробельная строка — нет
        if value and not value.strip():
            raise ValueError("Модель не может состоять из одних пробелов")
        return value.strip()


class AIConnectionTestRequest(BaseModel):
    """POST /api/ai-settings/test: текущие (возможно несохранённые) значения
    формы. Пустые поля разрешаются в сохранённое значение, затем в env."""

    protocol: str
    base_url: str = Field(default="", max_length=512)
    model: str = Field(default="", max_length=128)
    api_key: str = Field(default="", max_length=4096)

    @field_validator("protocol")
    @classmethod
    def protocol_known(cls, value: str) -> str:
        if value not in ("anthropic", "openai"):
            raise ValueError("Протокол должен быть anthropic или openai")
        return value


class AIConnectionTestResult(BaseModel):
    """Результат «Проверить подключение»: ошибка подключения — не сбой API."""

    ok: bool
    message: str


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


# --- Оценки руководителя по ИИ-критериям ---


class RatingItem(BaseModel):
    """Одна оценка в PUT: score=None — снять оценку («—»)."""

    criterion_id: int
    score: int | None = Field(default=None, ge=1, le=5)


class RatingsUpdate(BaseModel):
    """PUT /api/documents/{id}/ratings: применить оценки (upsert по паре
    документ+критерий). Достаточно изменившихся элементов, не всего блока."""

    ratings: list[RatingItem] = Field(min_length=1, max_length=100)

    @field_validator("ratings")
    @classmethod
    def no_duplicate_criteria(cls, value: list[RatingItem]) -> list[RatingItem]:
        seen = {item.criterion_id for item in value}
        if len(seen) != len(value):
            raise ValueError("Каждый критерий — не более одной оценки в запросе")
        return value


class RatingItemOut(BaseModel):
    """Критерий последнего прогона с оценкой руководителя (если есть)."""

    criterion_id: int
    code: str
    name: str
    is_archived: bool
    # None — оценка ещё не выставлена («—»)
    score: int | None = None
    updated_at: datetime | None = None
    # Документ перепроверен после оценки — оценка могла устареть
    stale: bool = False


class RatingsOut(BaseModel):
    """Блок оценивания документа: критерии последнего прогона в его порядке.

    Пустой criteria — прогона с ИИ-проверкой ещё не было (или отчёт старый,
    до появления критериев): оценивать нечего.
    """

    document_id: int
    criteria: list[RatingItemOut] = Field(default_factory=list)


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
