"""Конфигурация сервиса (НФТ: секреты только из окружения, никогда из кода)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # В .env могут лежать посторонние переменные (POSTGRES_* и т.п.)
        extra="ignore",
    )

    app_name: str = "Confluence Reviewer"
    app_version: str = "1.0.0"

    # БД
    database_url: str = "postgresql+psycopg2://confluence_reviewer:password@db:5432/confluence_reviewer"

    # Безопасность (НФТ-CR-7)
    auth_enabled: bool = True
    app_username: str = "reviewer"
    app_password: str = ""

    # Confluence
    confluence_base_url: str = ""
    confluence_auth_type: str = "bearer"  # bearer | basic
    confluence_token: str = ""
    confluence_username: str = ""
    confluence_password: str = ""
    # email | username | auto (email, затем локальная часть до @)
    confluence_creator_field: str = "auto"

    # Синхронизация
    sync_interval_hours: int = 24
    confluence_page_size: int = 25
    confluence_max_pages: int = 500
    confluence_request_delay: float = 0.2  # сек, НФТ-CR-6: <= 10 req/s

    # ИИ-валидация (GLM через Anthropic-совместимый API)
    ai_base_url: str = "https://api.z.ai/api/anthropic"
    ai_api_key: str = ""
    ai_model: str = "glm-4.5"
    ai_max_tokens: int = 4000
    ai_timeout_seconds: float = 180.0

    # Шаблон требований
    template_file: str = "app/templates/requirements_template.json"

    # Первичное наполнение: "ФИО:email;ФИО:email"
    seed_analysts: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
