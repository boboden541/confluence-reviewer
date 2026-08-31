"""Confluence-документы и заметки руководителя по ним."""

from __future__ import annotations

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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.validation import ValidationStatus
from app.utils import now_utc


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
    created_in_confluence_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_modified_in_confluence_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    validation_status: Mapped[ValidationStatus] = mapped_column(
        Enum(ValidationStatus), default=ValidationStatus.NOT_CHECKED, nullable=False, index=True
    )
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc, nullable=False
    )

    analyst: Mapped["Analyst"] = relationship(back_populates="documents")
    reports: Mapped[list["ValidationReport"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    note: Mapped["DocumentNote | None"] = relationship(
        back_populates="document", cascade="all, delete-orphan", uselist=False
    )


class DocumentNote(Base):
    """Заметки руководителя по документу в Markdown (ФТ-CR-18). Одна на документ."""

    __tablename__ = "document_notes"
    __table_args__ = (UniqueConstraint("document_id", name="uq_document_notes_document"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("confluence_documents.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc, nullable=False
    )

    document: Mapped[ConfluenceDocument] = relationship(back_populates="note")
