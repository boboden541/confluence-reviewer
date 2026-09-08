"""ИИ-часть домена: настройки подключения, критерии проверки, оценки руководителя."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils import now_utc


class AIConnectionSettings(Base):
    """Глобальные настройки подключения ИИ: одна строка (id=1).

    Пустое поле = значение из окружения (env — загрузочный дефолт).
    api_key хранится в БД (принятый компромисс внутреннего инструмента),
    наружу отдаётся только маской (см. usecase.ai_settings.mask_api_key).
    """

    __tablename__ = "ai_connection_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # NULL — настройка «по умолчанию» (одна, правит God); иначе — личная пользователя
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, unique=True, index=True
    )
    protocol: Mapped[str] = mapped_column(String(16), nullable=False, default="anthropic")
    base_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    api_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc, nullable=False
    )


class AiCriterion(Base):
    """Глобальный критерий ИИ-проверки: название + промт-инструкция.

    Промт ИИ-проверки собирается из активных критериев (диалог запуска);
    оценки руководителя по документам ссылаются на критерий FK. Удаление —
    логическое (is_archived): архив не участвует в новых проверках, но
    прошлые оценки и статистика сохраняют смысл.
    """

    __tablename__ = "ai_criteria"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Стабильный код (транслит названия при создании). Название дальше можно
    # менять свободно — старые оценки увидят новое название, код не меняется
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Что и как проверять; что считать провалом
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc, nullable=False
    )
    # владелец: критерии персональны; NULL — только до миграции (см. seed_auth)
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )


class CriterionRating(Base):
    """Оценка руководителя (1..10) по ИИ-критерию конкретного документа.

    Одна на пару документ+критерий; «—» (без оценки) — отсутствие записи:
    PUT со score=None удаляет её (статистика считает только реальные оценки).
    Оцениваются активные критерии справочника; архивный критерий скрыт из
    блока оценивания, но его прошлые оценки живут в БД и статистике.
    Записи не стираются при новых прогонах — актуальность каждой показывает
    сравнение updated_at с created_at отчёта (stale = документ перепроверен
    после оценки).
    """

    __tablename__ = "criterion_ratings"
    __table_args__ = (
        UniqueConstraint("document_id", "criterion_id", name="uq_criterion_ratings_pair"),
        # имя констрейнта — маркер миграции шкалы в database.py (было 1..5)
        CheckConstraint("score BETWEEN 1 AND 10", name="ck_criterion_ratings_score_1_10"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("confluence_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    criterion_id: Mapped[int] = mapped_column(
        ForeignKey("ai_criteria.id", ondelete="CASCADE"), nullable=False, index=True
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc, nullable=False
    )
