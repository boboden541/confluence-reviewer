"""Аналитики и заметки по ним (профиль)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils import now_utc


class Analyst(Base):
    """Карточка аналитика (ФТ-CR-1): минимум ФИО + email."""

    __tablename__ = "analysts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    # Переопределение имени пользователя Confluence, если оно не совпадает
    # с email / локальной частью email (БФТ 3.1 №13)
    confluence_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    documents: Mapped[list["ConfluenceDocument"]] = relationship(
        back_populates="analyst", cascade="all, delete-orphan"
    )
    note: Mapped["AnalystNote | None"] = relationship(
        back_populates="analyst", cascade="all, delete-orphan", uselist=False
    )


class AnalystNote(Base):
    """Заметка руководителя по аналитику в Markdown (профиль аналитика). Одна на аналитика."""

    __tablename__ = "analyst_notes"
    __table_args__ = (UniqueConstraint("analyst_id", name="uq_analyst_notes_analyst"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analyst_id: Mapped[int] = mapped_column(
        ForeignKey("analysts.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc, nullable=False
    )

    analyst: Mapped[Analyst] = relationship(back_populates="note")
