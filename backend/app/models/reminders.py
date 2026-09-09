"""Личные напоминания руководителя: «вернуться к аналитику/документу».

Напоминание строго личное: видит и управляет только владелец. Привязка
к аналитику обязательна, к документу — опциональна (контекст ревью).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils import now_utc


class Reminder(Base):
    """Напоминание: открытая → выполненная (done_at); удаление — вручную
    и только у выполненных (история ведётся, пока сам не удалит)."""

    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # владелец; чужие напоминания не видны в принципе (404)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    analyst_id: Mapped[int] = mapped_column(ForeignKey("analysts.id"), nullable=False, index=True)
    # опциональный контекст ревью: документ, к которому вернуться
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("confluence_documents.id"), nullable=True, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # дата «вернуться»; NULL — живёт в списке открытых без срока
    remind_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # NULL — открыта; дата — выполнена (статусная модель без отдельной колонки)
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
