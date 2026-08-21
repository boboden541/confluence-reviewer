"""Модель данных: аналитики, Confluence-документы, отчёты валидации, заметки."""

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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


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


class Analyst(Base):
    """Карточка аналитика (ФТ-CR-1): минимум ФИО + email."""

    __tablename__ = "analysts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    # Переопределение имени пользователя Confluence, если оно не совпадает
    # с email / локальной частью email (БФТ 3.1 №13)
    confluence_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    documents: Mapped[list[ConfluenceDocument]] = relationship(
        back_populates="analyst", cascade="all, delete-orphan"
    )


class ConfluenceDocument(Base):
    """Страница Confluence, созданная аналитиком (ФТ-CR-3, ФТ-CR-4)."""

    __tablename__ = "confluence_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analyst_id: Mapped[int] = mapped_column(
        ForeignKey("analysts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    confluence_page_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_in_confluence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_modified_in_confluence_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    validation_status: Mapped[ValidationStatus] = mapped_column(
        Enum(ValidationStatus), default=ValidationStatus.NOT_CHECKED, nullable=False, index=True
    )
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    analyst: Mapped[Analyst] = relationship(back_populates="documents")
    reports: Mapped[list[ValidationReport]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    note: Mapped[DocumentNote | None] = relationship(
        back_populates="document", cascade="all, delete-orphan", uselist=False
    )


class ValidationReport(Base):
    """Отчёт валидации: скриптовая проверка шаблона + ИИ-проверка содержания (ФТ-CR-16)."""

    __tablename__ = "validation_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("confluence_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    triggered_by: Mapped[TriggerType] = mapped_column(Enum(TriggerType), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    template_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    template_findings: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ai_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ai_findings: Mapped[str | None] = mapped_column(Text, nullable=True)
    overall_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    document: Mapped[ConfluenceDocument] = relationship(back_populates="reports")


class DocumentNote(Base):
    """Заметки руководителя по документу в Markdown (ФТ-CR-18). Одна на документ."""

    __tablename__ = "document_notes"
    __table_args__ = (UniqueConstraint("document_id", name="uq_document_notes_document"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("confluence_documents.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    document: Mapped[ConfluenceDocument] = relationship(back_populates="note")
