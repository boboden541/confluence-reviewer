"""Организационная структура: кластеры и команды (иерархия над аналитиками).

Кластер объединяет команды; команда объединяет аналитиков. Аналитик состоит
ровно в одной команде (analysts.team_id) — привязка живёт на стороне
аналитика, поэтому удаление команды не трогает его документы: usecase
сначала отвязывает участников, потом удаляет запись. Кластер удалить нельзя,
пока в нём есть команды (guard в usecase).
"""

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
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils import now_utc


class Cluster(Base):
    """Кластер (верхний уровень структуры): объединяет команды."""

    __tablename__ = "clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # цвет из палитры UI (hex) — кодирует кластер в дереве и на картах;
    # NULL — фронт подставляет нейтральный по порядку создания
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)


class Team(Base):
    """Команда внутри кластера: объединяет аналитиков."""

    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("cluster_id", "name", name="uq_teams_cluster_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster_id: Mapped[int] = mapped_column(
        ForeignKey("clusters.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
