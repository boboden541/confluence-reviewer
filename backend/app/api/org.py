"""Организационная структура: кластеры и команды (/api/clusters, /api/teams).

Тонкий слой над usecase.org: парсинг входа и перевод доменных исключений
в HTTP-ответы (404 — NotFound, 409 — Taken/NotEmpty). Удаление команды
 отвязывает участников; удаление непустого кластера — 409.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_permission
from app.models import User
from app.schemas import (
    ClusterCreate,
    ClusterOut,
    ClusterUpdate,
    TeamAnalystAdd,
    TeamCreate,
    TeamOut,
    TeamUpdate,
)
from app.usecase import org as org_uc
from app.usecase.exceptions import (
    AnalystNotFound,
    ClusterNameTaken,
    ClusterNotFound,
    ClusterNotEmpty,
    TeamNameTaken,
    TeamNotFound,
)

clusters_router = APIRouter(prefix="/api/clusters", tags=["clusters"])
teams_router = APIRouter(prefix="/api/teams", tags=["teams"])


# --- кластеры ---


@clusters_router.get("", response_model=list[ClusterOut])
def list_clusters(db: Session = Depends(get_db)):
    """Карта кластеров: кластеры с командами и счётчиками (аналитики, документы)."""
    return org_uc.list_clusters(db)


@clusters_router.post("", response_model=ClusterOut, status_code=status.HTTP_201_CREATED)
def create_cluster(payload: ClusterCreate, db: Session = Depends(get_db)):
    """Новый кластер; название уникально."""
    try:
        return org_uc.create_cluster(db, payload)
    except ClusterNameTaken as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@clusters_router.get("/{cluster_id}", response_model=ClusterOut)
def get_cluster(cluster_id: int, db: Session = Depends(get_db)):
    try:
        return org_uc.get_cluster_view(db, cluster_id)
    except ClusterNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Кластер не найден") from exc


@clusters_router.put("/{cluster_id}", response_model=ClusterOut)
def update_cluster(cluster_id: int, payload: ClusterUpdate, db: Session = Depends(get_db)):
    try:
        return org_uc.update_cluster(db, cluster_id, payload)
    except ClusterNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Кластер не найден") from exc
    except ClusterNameTaken as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@clusters_router.delete("/{cluster_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cluster(
    cluster_id: int,
    db: Session = Depends(get_db),
    _: User | None = Depends(require_permission("delete")),
):
    """Удалить кластер. Пока в нём есть команды — 409."""
    try:
        org_uc.delete_cluster(db, cluster_id)
    except ClusterNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Кластер не найден") from exc
    except ClusterNotEmpty as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


# --- команды ---


@teams_router.post("", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
def create_team(payload: TeamCreate, db: Session = Depends(get_db)):
    """Новая команда в кластере; название уникально внутри кластера."""
    try:
        return org_uc.create_team(db, payload)
    except ClusterNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Кластер не найден") from exc
    except TeamNameTaken as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@teams_router.get("/{team_id}", response_model=TeamOut)
def get_team(team_id: int, db: Session = Depends(get_db)):
    """Команда с составом и агрегированными доменами участников."""
    try:
        return org_uc.get_team_view(db, team_id)
    except TeamNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Команда не найдена") from exc


@teams_router.put("/{team_id}", response_model=TeamOut)
def update_team(team_id: int, payload: TeamUpdate, db: Session = Depends(get_db)):
    try:
        return org_uc.update_team(db, team_id, payload)
    except TeamNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Команда не найдена") from exc
    except TeamNameTaken as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@teams_router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(
    team_id: int,
    db: Session = Depends(get_db),
    _: User | None = Depends(require_permission("delete")),
):
    """Удалить команду: аналитики остаются («без команды») со своими доменами,
    документами и оценками."""
    try:
        org_uc.delete_team(db, team_id)
    except TeamNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Команда не найдена") from exc


@teams_router.post("/{team_id}/analysts", response_model=TeamOut)
def add_analyst(team_id: int, payload: TeamAnalystAdd, db: Session = Depends(get_db)):
    """Привязать аналитиков к команде (одного или нескольких); домены
    обновляются, если переданы."""
    try:
        return org_uc.add_analyst(db, team_id, payload.analyst_ids, payload.domains)
    except TeamNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Команда не найдена") from exc
    except AnalystNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Аналитик не найден") from exc


@teams_router.delete("/{team_id}/analysts/{analyst_id}", response_model=TeamOut)
def remove_analyst(team_id: int, analyst_id: int, db: Session = Depends(get_db)):
    """Убрать аналитика из команды (идемпотентно)."""
    try:
        return org_uc.remove_analyst(db, team_id, analyst_id)
    except TeamNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Команда не найдена") from exc
