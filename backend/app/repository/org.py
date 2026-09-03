"""Выборки организационной структуры: кластеры, команды, составы.

Запись (add/commit) — в usecase.org; здесь только чтение. Счётчики —
подзапросами (по образцу repository.analysts.list_with_documents_count).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Analyst, Cluster, ConfluenceDocument, Team


def get_cluster(db: Session, cluster_id: int) -> Cluster | None:
    return db.get(Cluster, cluster_id)


def list_clusters(db: Session) -> list[Cluster]:
    """Кластеры по алфавиту (сортировку карточек добирает usecase при нужде)."""
    return list(db.scalars(select(Cluster).order_by(Cluster.name)).all())


def cluster_name_taken(db: Session, name: str, exclude_id: int | None = None) -> bool:
    condition = Cluster.name == name
    if exclude_id is not None:
        condition = condition & (Cluster.id != exclude_id)
    return db.scalar(select(Cluster.id).where(condition)) is not None


def list_teams(db: Session, cluster_id: int) -> list[Team]:
    """Команды кластера по алфавиту."""
    return list(
        db.scalars(select(Team).where(Team.cluster_id == cluster_id).order_by(Team.name)).all()
    )


def get_team(db: Session, team_id: int) -> Team | None:
    return db.get(Team, team_id)


def team_name_taken(db: Session, cluster_id: int, name: str, exclude_id: int | None = None) -> bool:
    """Дубль названия команды внутри кластера; exclude_id — при редактировании."""
    condition = Team.cluster_id == cluster_id
    condition = condition & (func.lower(Team.name) == func.lower(name))
    if exclude_id is not None:
        condition = condition & (Team.id != exclude_id)
    return db.scalar(select(Team.id).where(condition)) is not None


def teams_count(db: Session, cluster_id: int) -> int:
    return (
        db.scalar(select(func.count()).select_from(Team).where(Team.cluster_id == cluster_id))
        or 0
    )


def analysts_count(db: Session, cluster_id: int) -> int:
    """Аналитики кластера = участники всех его команд."""
    return (
        db.scalar(
            select(func.count())
            .select_from(Analyst)
            .join(Team, Analyst.team_id == Team.id)
            .where(Team.cluster_id == cluster_id)
        )
        or 0
    )


def documents_count(db: Session, cluster_id: int) -> int:
    """Документы кластера = документы аналитиков его команд."""
    return (
        db.scalar(
            select(func.count())
            .select_from(ConfluenceDocument)
            .join(Analyst, ConfluenceDocument.analyst_id == Analyst.id)
            .join(Team, Analyst.team_id == Team.id)
            .where(Team.cluster_id == cluster_id)
        )
        or 0
    )


def team_analysts_count(db: Session, team_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Analyst).where(Analyst.team_id == team_id)) or 0
