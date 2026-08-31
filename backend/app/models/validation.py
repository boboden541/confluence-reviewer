"""Отчёты валидации и их статусная модель."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils import now_utc


class ValidationStatus(str, enum.Enum):
    """Статусная модель проверки (ФТ-CR-15)."""

    NOT_CHECKED = "not_checked"      # не проверено
    IN_PROGRESS = "in_progress"      # проверяется
    PASSED = "passed"                # проверки пройдены
    FAILED = "failed"                # проверки не пройдены
    ERROR = "error"                  # ошибка


class TriggerType(str, enum.Enum):
    AUTO = "auto"
    MANUAL = "manual"


class ValidationReport(Base):
    """Отчёт валидации: скриптовая проверка шаблона + ИИ-проверка содержания (ФТ-CR-16)."""

    __tablename__ = "validation_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("confluence_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    triggered_by: Mapped[TriggerType] = mapped_column(Enum(TriggerType), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    # NULL — проверка шаблона не запускалась (выбор критериев в диалоге проверки)
    template_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    template_findings: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ai_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ai_findings: Mapped[str | None] = mapped_column(Text, nullable=True)
    overall_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Какой версией шаблона проверяли (NULL — старые отчёты и проверки без выбора)
    template_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("template_versions.id", ondelete="SET NULL"), nullable=True
    )
    # Пользовательский промт ИИ этой проверки (NULL — собран из критериев)
    ai_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Критерии, из которых собран промт прогона (JSON-список кодов; NULL — старые)
    ai_criteria_codes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Хэш эффективного промта (override или собранного): отличие = перевалидация
    ai_prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Какой моделью выполнялась ИИ-проверка (NULL — старые отчёты). Отличие
    # эффективной модели от этого значения = перевалидация (ФТ-CR-14)
    ai_model_used: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Когда замечания этого отчёта были опубликованы комментарием в Confluence (ФТ-CR-17)
    comment_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    document: Mapped["ConfluenceDocument"] = relationship(back_populates="reports")
