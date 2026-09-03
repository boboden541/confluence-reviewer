"""Организационная структура: кластеры и команды над аналитиками.

Аналитик состоит ровно в одной команде (analysts.team_id); его домены —
свободные теги (JSON-список в analysts.domains). Домены команды на экране —
уникальные домены её участников. Удаление команды отвязывает участников
(документы/отчёты/оценки не трогаются); удаление кластера запрещено, пока
в нём есть команды.
"""

from __future__ import annotations

import json

from app import repository
from app.models import Analyst, Cluster, Team
from app.schemas import (
    AnalystBrief,
    ClusterCreate,
    ClusterOut,
    ClusterUpdate,
    TeamBrief,
    TeamCreate,
    TeamOut,
    TeamUpdate,
)
from app.usecase.exceptions import (
    AnalystNotFound,
    ClusterNameTaken,
    ClusterNotFound,
    ClusterNotEmpty,
    TeamNameTaken,
    TeamNotFound,
)


def _analyst_domains(analyst: Analyst) -> list[str]:
    """Домены аналитика из JSON-колонки; битое значение = пустой список."""
    try:
        raw = json.loads(analyst.domains or "[]")
    except ValueError:
        return []
    return [d for d in raw if isinstance(d, str) and d.strip()]


def normalize_domains(raw: list[str]) -> list[str]:
    """Теги: trim, без пустых и дублей (без учёта регистра), порядок сохранён."""
    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        value = item.strip()
        key = value.lower()
        if not value or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _domains_json(domains: list[str]) -> str:
    return json.dumps(domains, ensure_ascii=False)


def _team_domains(analysts: list[Analyst]) -> list[str]:
    """Уникальные домены команды: объединение доменов участников (правила
    нормализации те же, что у одиночного списка)."""
    return normalize_domains([d for analyst in analysts for d in _analyst_domains(analyst)])


def _to_brief(analyst: Analyst, doc_counts: dict[int, int]) -> AnalystBrief:
    return AnalystBrief(
        id=analyst.id,
        full_name=analyst.full_name,
        email=analyst.email,
        documents_count=doc_counts.get(analyst.id, 0),
        domains=_analyst_domains(analyst),
    )


# --- кластеры ---


def _cluster_out(
    db,
    cluster: Cluster,
    stats: dict[int, tuple[int, int, int]],
    team_counts: dict[int, int],
) -> ClusterOut:
    teams = repository.org.list_teams(db, cluster.id)
    teams_n, analysts_n, documents_n = stats.get(cluster.id, (0, 0, 0))
    return ClusterOut(
        id=cluster.id,
        name=cluster.name,
        description=cluster.description,
        color=cluster.color,
        created_at=cluster.created_at,
        teams_count=teams_n,
        analysts_count=analysts_n,
        documents_count=documents_n,
        teams=[
            TeamBrief(
                id=team.id,
                name=team.name,
                description=team.description,
                analysts_count=team_counts.get(team.id, 0),
            )
            for team in teams
        ],
    )


def _get_cluster(db, cluster_id: int) -> Cluster:
    cluster = repository.org.get_cluster(db, cluster_id)
    if cluster is None:
        raise ClusterNotFound(f"Кластер {cluster_id} не найден")
    return cluster


def list_clusters(db) -> list[ClusterOut]:
    """Все кластеры по алфавиту, с командами и счётчиками (батчево: три
    групповых запроса на счётчики + один на составы, без N+1)."""
    stats = repository.org.cluster_stats(db)
    team_counts = repository.org.team_analyst_counts(db)
    return [
        _cluster_out(db, cluster, stats, team_counts)
        for cluster in repository.org.list_clusters(db)
    ]


def get_cluster_view(db, cluster_id: int) -> ClusterOut:
    stats = repository.org.cluster_stats(db)
    team_counts = repository.org.team_analyst_counts(db)
    return _cluster_out(db, _get_cluster(db, cluster_id), stats, team_counts)


def create_cluster(db, payload: ClusterCreate) -> ClusterOut:
    """Новый кластер; название уникально."""
    name = payload.name.strip()
    if repository.org.cluster_name_taken(db, name):
        raise ClusterNameTaken(f"Кластер «{name}» уже существует")
    cluster = Cluster(
        name=name,
        description=payload.description,
        color=payload.color,
    )
    db.add(cluster)
    db.commit()
    db.refresh(cluster)
    return _cluster_out(db, cluster, repository.org.cluster_stats(db), repository.org.team_analyst_counts(db))


def update_cluster(db, cluster_id: int, payload: ClusterUpdate) -> ClusterOut:
    """Редактирование кластера (название, описание, цвет)."""
    cluster = _get_cluster(db, cluster_id)
    name = payload.name.strip()
    if repository.org.cluster_name_taken(db, name, exclude_id=cluster_id):
        raise ClusterNameTaken(f"Кластер «{name}» уже существует")
    cluster.name = name
    cluster.description = payload.description
    cluster.color = payload.color
    db.commit()
    db.refresh(cluster)
    return _cluster_out(db, cluster, repository.org.cluster_stats(db), repository.org.team_analyst_counts(db))


def delete_cluster(db, cluster_id: int) -> None:
    """Удалить кластер; сначала нужно удалить его команды (guard ниже)."""
    cluster = _get_cluster(db, cluster_id)
    if repository.org.teams_count(db, cluster.id):
        raise ClusterNotEmpty("Сначала удалите команды кластера")
    db.delete(cluster)
    db.commit()


# --- команды ---


def _team_out(db, team: Team) -> TeamOut:
    cluster = repository.org.get_cluster(db, team.cluster_id)
    members = repository.analysts.list_by_team(db, team.id)
    doc_counts = repository.org.documents_count_map(db, [member.id for member in members])
    return TeamOut(
        id=team.id,
        cluster_id=team.cluster_id,
        cluster_name=cluster.name if cluster else "?",
        cluster_color=cluster.color if cluster else None,
        name=team.name,
        description=team.description,
        created_at=team.created_at,
        analysts=[_to_brief(analyst, doc_counts) for analyst in members],
        domains=_team_domains(members),
    )


def _get_team(db, team_id: int) -> Team:
    team = repository.org.get_team(db, team_id)
    if team is None:
        raise TeamNotFound(f"Команда {team_id} не найдена")
    return team


def get_team_view(db, team_id: int) -> TeamOut:
    """Команда с составом и агрегированными доменами участников."""
    return _team_out(db, _get_team(db, team_id))


def create_team(db, payload: TeamCreate) -> TeamOut:
    """Новая команда в кластере; название уникально внутри кластера."""
    _get_cluster(db, payload.cluster_id)  # 404, если кластера нет
    name = payload.name.strip()
    if repository.org.team_name_taken(db, payload.cluster_id, name):
        raise TeamNameTaken(f"Команда «{name}» уже есть в этом кластере")
    team = Team(
        cluster_id=payload.cluster_id,
        name=name,
        description=payload.description,
    )
    db.add(team)
    db.commit()
    db.refresh(team)
    return _team_out(db, team)


def update_team(db, team_id: int, payload: TeamUpdate) -> TeamOut:
    """Редактирование команды (название, описание); кластер не переносится."""
    team = _get_team(db, team_id)
    name = payload.name.strip()
    if repository.org.team_name_taken(db, team.cluster_id, name, exclude_id=team_id):
        raise TeamNameTaken(f"Команда «{name}» уже есть в этом кластере")
    team.name = name
    team.description = payload.description
    db.commit()
    db.refresh(team)
    return _team_out(db, team)


def delete_team(db, team_id: int) -> None:
    """Удалить команду: участники остаются («без команды») со своими доменами,
    документами и оценками."""
    team = _get_team(db, team_id)
    for analyst in repository.analysts.list_by_team(db, team.id):
        analyst.team_id = None
    db.delete(team)
    db.commit()


# --- состав команды и домены ---


def add_analyst(db, team_id: int, analyst_id: int, domains: list[str] | None) -> TeamOut:
    """Привязать аналитика к команде (или обновить домены, если он уже в ней).

    Аналитик из другой команды переводится: прежняя привязка заменяется,
    домены перезаписываются присланным набором (пусто — очистить).
    """
    team = _get_team(db, team_id)
    analyst = repository.analysts.get(db, analyst_id)
    if analyst is None:
        raise AnalystNotFound(f"Аналитик {analyst_id} не найден")
    analyst.team_id = team.id
    if domains is not None:
        analyst.domains = _domains_json(normalize_domains(domains))
    db.commit()
    return _team_out(db, team)


def remove_analyst(db, team_id: int, analyst_id: int) -> TeamOut:
    """Убрать аналитика из команды (team_id=None); идемпотентно."""
    _get_team(db, team_id)
    analyst = repository.analysts.get(db, analyst_id)
    if analyst is not None and analyst.team_id == team_id:
        analyst.team_id = None
        db.commit()
    return _team_out(db, _get_team(db, team_id))


def set_analyst_domains(db, analyst_id: int, domains: list[str]) -> list[str]:
    """Перезаписать домены аналитика; возвращает применённый список."""
    analyst = repository.analysts.get(db, analyst_id)
    if analyst is None:
        raise AnalystNotFound(f"Аналитик {analyst_id} не найден")
    applied = normalize_domains(domains)
    analyst.domains = _domains_json(applied)
    db.commit()
    return applied
