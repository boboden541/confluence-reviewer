"""Выборки отчётов валидации."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ValidationReport


def get_latest(db: Session, document_id: int) -> ValidationReport | None:
    """Последний отчёт валидации документа (свежие created_at, затем id)."""
    return db.scalar(
        select(ValidationReport)
        .where(ValidationReport.document_id == document_id)
        .order_by(ValidationReport.created_at.desc(), ValidationReport.id.desc())
    )
