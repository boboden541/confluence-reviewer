"""Шаблоны требований: контейнер-цепочка версий."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils import now_utc


class Template(Base):
    """Шаблон требований: контейнер цепочки версий (ФТ-CR-10).

    Пометка «по умолчанию» (предвыбор в диалоге проверки) и архив живут на
    контейнере; name/description редактируются версиями — история сохраняет,
    как шаблон назывался в момент каждой проверки. Физического удаления нет:
    архив убирает шаблон из выбора, но карточка, версии и отчёты живут."""

    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Предвыбор в диалоге проверки; ровно одна среди неархивных (переключение
    # переносит пометку). Может не быть ни одной — тогда диалог предвыбирает первый
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    # NULL — активный шаблон; дата — в архиве (не участвует в выборе при проверке)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    # владелец: шаблоны персональны; NULL — только до миграции (см. seed_auth)
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )

    versions: Mapped[list["TemplateVersion"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )


class TemplateVersion(Base):
    """Версия шаблона требований (ФТ-CR-10). Каждое сохранение из UI создаёт
    новую версию; активна ровно одна ВНУТРИ шаблона (is_active).

    Секции хранятся плоским списком в визуальном порядке — вложенность
    задаётся уровнем 1..3 (см. usecase.templates).
    """

    __tablename__ = "template_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Контейнер-шаблон. Nullable — колонка добавляется миграцией к существующим
    # строкам; сервис всегда заполняет её (миграция оборачивает старую цепочку
    # в первый шаблон)
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("templates.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Маркер названия: буквальное вхождение отдельным словом, без учёта регистра
    title_marker: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    sections_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # Повторяемые блоки доработок: не редактируются из UI, переносятся из
    # версии в версию (первая версия сеется из JSON-файла)
    repeatable_blocks_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # Активная версия — внутри своего шаблона (не глобально)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)

    template: Mapped[Template | None] = relationship(back_populates="versions")
