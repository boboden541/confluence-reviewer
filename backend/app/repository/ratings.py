"""Выборки оценок руководителя."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AiCriterion, ConfluenceDocument, CriterionRating


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


def summary_by_analyst(
    db: Session,
    analyst_id: int,
    date_from=None,
    date_to=None,
) -> list:
    """Средняя оценка и число оценок по каждому критерию аналитика.

    Период — по дате создания документа в Confluence; границы уже
    нормализованы usecase'ом (наивный UTC, «по» — конец дня).
    """
    query = (
        select(
            AiCriterion.id,
            AiCriterion.code,
            AiCriterion.name,
            AiCriterion.is_archived,
            func.avg(CriterionRating.score).label("average"),
            func.count().label("ratings_count"),
        )
        .join(ConfluenceDocument, CriterionRating.document_id == ConfluenceDocument.id)
        .join(AiCriterion, CriterionRating.criterion_id == AiCriterion.id)
        .where(ConfluenceDocument.analyst_id == analyst_id)
        .group_by(AiCriterion.id, AiCriterion.code, AiCriterion.name, AiCriterion.is_archived)
    )
    if date_from is not None:
        query = query.where(ConfluenceDocument.created_in_confluence_at >= date_from)
    if date_to is not None:
        query = query.where(ConfluenceDocument.created_in_confluence_at <= date_to)
    return list(db.execute(query).all())
