"""Выборки аналитиков и их заметок."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Analyst, AnalystNote, ConfluenceDocument


def get(db: Session, analyst_id: int) -> Analyst | None:
    return db.get(Analyst, analyst_id)


def list_ids(db: Session) -> list[int]:
    """id всех аналитиков по возрастанию (полная синхронизация)."""
    return list(db.scalars(select(Analyst.id).order_by(Analyst.id)).all())


def list_with_documents_count(db: Session) -> list[tuple[Analyst, int]]:
    """Аналитики по алфавиту с числом документов (одним запросом)."""
    count_sq = (
        select(ConfluenceDocument.analyst_id, func.count().label("cnt"))
        .group_by(ConfluenceDocument.analyst_id)
        .subquery()
    )
    return list(
        db.execute(
            select(Analyst, func.coalesce(count_sq.c.cnt, 0).label("documents_count"))
            .outerjoin(count_sq, count_sq.c.analyst_id == Analyst.id)
            .order_by(Analyst.full_name)
        ).all()
    )


def get_by_email(db: Session, email: str, exclude_id: int | None = None) -> Analyst | None:
    """Аналитик по email; exclude_id — проверка дубля при редактировании."""
    condition = Analyst.email == email
    if exclude_id is not None:
        condition = condition & (Analyst.id != exclude_id)
    return db.scalar(select(Analyst).where(condition))


def count_documents(db: Session, analyst_id: int) -> int:
    """Число документов аналитика (для карточки)."""
    return (
        db.scalar(
            select(func.count())
            .select_from(ConfluenceDocument)
            .where(ConfluenceDocument.analyst_id == analyst_id)
        )
        or 0
    )


def get_note(db: Session, analyst_id: int) -> AnalystNote | None:
    """Заметка аналитика (одна на аналитика)."""
    return db.scalar(select(AnalystNote).where(AnalystNote.analyst_id == analyst_id))


def list_by_team(db: Session, team_id: int) -> list[Analyst]:
    """Участники команды по алфавиту (состав, отвязка при удалении команды)."""
    return list(
        db.scalars(
            select(Analyst).where(Analyst.team_id == team_id).order_by(Analyst.full_name)
        ).all()
    )
