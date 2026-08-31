"""Выборки справочника ИИ-критериев."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AiCriterion


def list_all(db: Session) -> list[AiCriterion]:
    """Все критерии: активные, затем архивные (справочник в настройках)."""
    return list(
        db.scalars(
            select(AiCriterion).order_by(AiCriterion.is_archived, AiCriterion.id)
        ).all()
    )


def list_active(db: Session) -> list[AiCriterion]:
    """Активные критерии в порядке справочника."""
    return list(
        db.scalars(
            select(AiCriterion)
            .where(AiCriterion.is_archived.is_(False))
            .order_by(AiCriterion.id)
        ).all()
    )


def get(db: Session, criterion_id: int) -> AiCriterion | None:
    return db.get(AiCriterion, criterion_id)


def code_exists(db: Session, code: str) -> bool:
    return db.scalar(select(AiCriterion.id).where(AiCriterion.code == code)) is not None


def any_exists(db: Session) -> bool:
    return db.scalar(select(AiCriterion.id).limit(1)) is not None
