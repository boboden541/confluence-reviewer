"""Выборки оценок руководителя."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CriterionRating


def list_for_document(db: Session, document_id: int) -> list[CriterionRating]:
    """Все оценки документа (критерий → запись, включая архивные критерии)."""
    return list(
        db.scalars(
            select(CriterionRating).where(CriterionRating.document_id == document_id)
        ).all()
    )


def get(db: Session, document_id: int, criterion_id: int) -> CriterionRating | None:
    """Оценка по паре документ+критерий (upsert ищет по ней)."""
    return db.scalar(
        select(CriterionRating).where(
            CriterionRating.document_id == document_id,
            CriterionRating.criterion_id == criterion_id,
        )
    )
