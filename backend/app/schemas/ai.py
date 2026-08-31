"""Схемы справочника ИИ-критериев и настроек подключения ИИ."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
