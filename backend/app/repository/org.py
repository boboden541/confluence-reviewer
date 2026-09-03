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
    """Дубль названия кластера без учёта регистра (как у команд)."""
    condition = func.lower(Cluster.name) == func.lower(name)
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
    """Число команд кластера (guard удаления кластера)."""
    return (
        db.scalar(select(func.count()).select_from(Team).where(Team.cluster_id == cluster_id))
        or 0
    )


# --- батчевые выборки для карт и списков (вместо N+1 по одному объекту) ---


def team_contexts(db: Session) -> dict[int, tuple[str, int, str, str | None]]:
    """Команда → (название, id кластера, название кластера, цвет кластера)
    одним join-запросом: карточки аналитиков enrich'ятся без point-lookups."""
    rows = db.execute(
        select(Team.id, Team.name, Cluster.id, Cluster.name, Cluster.color).join(
            Cluster, Team.cluster_id == Cluster.id
        )
    ).all()
    return {
        team_id: (team_name, cluster_id, cluster_name, cluster_color)
        for team_id, team_name, cluster_id, cluster_name, cluster_color in rows
    }


def cluster_stats(db: Session) -> dict[int, tuple[int, int, int]]:
    """Кластер → (команд, аналитиков, документов) тремя групповыми запросами."""
    teams_sq = (
        select(Team.cluster_id, func.count().label("cnt"))
        .group_by(Team.cluster_id)
        .subquery()
    )
    analysts_sq = (
        select(Team.cluster_id, func.count().label("cnt"))
        .select_from(Analyst)
        .join(Team, Analyst.team_id == Team.id)
        .group_by(Team.cluster_id)
        .subquery()
    )
    documents_sq = (
        select(Team.cluster_id, func.count().label("cnt"))
        .select_from(ConfluenceDocument)
        .join(Analyst, ConfluenceDocument.analyst_id == Analyst.id)
        .join(Team, Analyst.team_id == Team.id)
        .group_by(Team.cluster_id)
        .subquery()
    )
    team_counts = dict(db.execute(select(teams_sq.c.cluster_id, teams_sq.c.cnt)).all())
    analyst_counts = dict(db.execute(select(analysts_sq.c.cluster_id, analysts_sq.c.cnt)).all())
    document_counts = dict(db.execute(select(documents_sq.c.cluster_id, documents_sq.c.cnt)).all())
    cluster_ids = set(team_counts) | set(analyst_counts) | set(document_counts)
    return {
        cluster_id: (
            team_counts.get(cluster_id, 0),
            analyst_counts.get(cluster_id, 0),
            document_counts.get(cluster_id, 0),
        )
        for cluster_id in cluster_ids
    }


def team_analyst_counts(db: Session) -> dict[int, int]:
    """Команда → число участников одним групповым запросом."""
    rows = db.execute(
        select(Analyst.team_id, func.count()).where(Analyst.team_id.is_not(None)).group_by(Analyst.team_id)
    ).all()
    return {team_id: count for team_id, count in rows}


def documents_count_map(db: Session, analyst_ids: list[int]) -> dict[int, int]:
    """Аналитик → число документов одним групповым запросом."""
    if not analyst_ids:
        return {}
    rows = db.execute(
        select(ConfluenceDocument.analyst_id, func.count())
        .where(ConfluenceDocument.analyst_id.in_(analyst_ids))
        .group_by(ConfluenceDocument.analyst_id)
    ).all()
    return dict(rows)
