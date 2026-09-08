"""Выборки для очереди внимания на главной.

Приоритет секций (документ попадает только в первую подходящую):
провал/ошибка → устарел после правки → ждёт оценки. Справочники и
аналитики без команды собираются из своих таблиц.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Analyst,
    ConfluenceDocument,
    CriterionRating,
    ValidationReport,
    ValidationStatus,
)


def failed_docs(
    db: Session, limit: int = 8, lead_user_id: int | None = None
) -> list[tuple[ConfluenceDocument, ValidationReport | None]]:
    """Проваленные/ошибочные документы, свежие сверху, + их последний отчёт."""
    docs = list(
        db.scalars(
            select(ConfluenceDocument)
            .where(*_failed_condition(lead_user_id))
            .order_by(
                ConfluenceDocument.last_validated_at.desc().nullslast(),
                ConfluenceDocument.id.desc(),
            )
            .limit(limit)
        ).all()
    )
    if not docs:
        return []
    reports = _latest_reports(db, [doc.id for doc in docs])
    return [(doc, reports.get(doc.id)) for doc in docs]


def failed_total(db: Session, lead_user_id: int | None = None) -> int:
    return _count_docs(db, *_failed_condition(lead_user_id))


def stale_docs(
    db: Session, limit: int = 8, lead_user_id: int | None = None
) -> list[tuple[ConfluenceDocument, datetime | None]]:
    """Документы «не проверено» с историей проверок: страницу правнули после
    ревью. at — момент последней известной правки."""
    conditions = [*_stale_condition()]
    lead = _lead_filter(lead_user_id)
    if lead is not None:
        conditions.append(lead)
    docs = list(
        db.scalars(
            select(ConfluenceDocument)
            .where(*conditions)
            .order_by(ConfluenceDocument.last_modified_in_confluence_at.desc().nullslast())
            .limit(limit)
        ).all()
    )
    return [(doc, doc.last_modified_in_confluence_at) for doc in docs]


def stale_total(db: Session, lead_user_id: int | None = None) -> int:
    conditions = [*_stale_condition()]
    lead = _lead_filter(lead_user_id)
    if lead is not None:
        conditions.append(lead)
    return _count_docs(db, *conditions)


def awaiting_ratings(
    db: Session, limit: int = 8, lead_user_id: int | None = None
) -> list[tuple[ConfluenceDocument, ValidationReport, datetime | None]]:
    """Документы, чей последний успешный ИИ-прогон не оценён или оценён
    устаревше (оценка старше отчёта). Возвращает (документ, отчёт, момент
    последней оценки)."""
    rows = db.execute(_awaiting_query(lead_user_id).limit(limit)).all()
    return [(doc, report, last_rated) for doc, report, last_rated in rows]


def awaiting_ratings_total(db: Session, lead_user_id: int | None = None) -> int:
    return db.scalar(
        select(func.count()).select_from(_awaiting_query(lead_user_id).subquery())
    ) or 0


def analysts_without_team(db: Session, limit: int = 8) -> list[tuple[Analyst, int]]:
    """Аналитики вне структуры: имя + число документов, по ФИО."""
    count_sq = (
        select(ConfluenceDocument.analyst_id, func.count().label("cnt"))
        .group_by(ConfluenceDocument.analyst_id)
        .subquery()
    )
    rows = db.execute(
        select(Analyst, func.coalesce(count_sq.c.cnt, 0))
        .outerjoin(count_sq, count_sq.c.analyst_id == Analyst.id)
        .where(Analyst.team_id.is_(None))
        .order_by(Analyst.full_name)
        .limit(limit)
    ).all()
    return [(analyst, count) for analyst, count in rows]


def analysts_without_team_total(db: Session) -> int:
    return db.scalar(
        select(func.count()).select_from(Analyst).where(Analyst.team_id.is_(None))
    ) or 0


def _lead_filter(lead_user_id: int | None):
    """Ограничение документов аналитиками, которых курирует лид (None — без
    фильтра: God и выключенная авторизация видят всю очередь)."""
    if lead_user_id is None:
        return None
    analyst_sq = select(Analyst.id).where(Analyst.lead_user_id == lead_user_id)
    return ConfluenceDocument.analyst_id.in_(analyst_sq)


def _failed_condition(lead_user_id: int | None = None):
    conditions = [ConfluenceDocument.validation_status.in_(
        (ValidationStatus.FAILED, ValidationStatus.ERROR)
    )]
    lead = _lead_filter(lead_user_id)
    if lead is not None:
        conditions.append(lead)
    return conditions


def _stale_condition():
    """«Не проверено» + была хоть одна успешная проверка (есть отчёт)."""
    has_report_sq = (
        select(ValidationReport.id)
        .where(
            ValidationReport.document_id == ConfluenceDocument.id,
            ValidationReport.error_message.is_(None),
        )
        .exists()
    )
    return (
        ConfluenceDocument.validation_status == ValidationStatus.NOT_CHECKED,
        has_report_sq,
    )


def _awaiting_query(lead_user_id: int | None = None):
    """Запрос документов, ждущих оценки: последний успешный ИИ-отчёт есть,
    оценок нет либо все они старше отчёта. Момент последней оценки — в довесок."""
    latest_ai_sq = (
        select(
            ValidationReport.document_id,
            func.max(ValidationReport.id).label("report_id"),
        )
        .where(
            ValidationReport.ai_passed.is_not(None),
            ValidationReport.error_message.is_(None),
        )
        .group_by(ValidationReport.document_id)
        .subquery()
    )
    rating_sq = (
        select(
            CriterionRating.document_id,
            func.count().label("ratings_count"),
            func.max(CriterionRating.updated_at).label("last_rated_at"),
        )
        .group_by(CriterionRating.document_id)
        .subquery()
    )
    query = (
        select(ConfluenceDocument, ValidationReport, rating_sq.c.last_rated_at)
        .join(latest_ai_sq, latest_ai_sq.c.document_id == ConfluenceDocument.id)
        .join(ValidationReport, ValidationReport.id == latest_ai_sq.c.report_id)
        .outerjoin(rating_sq, rating_sq.c.document_id == ConfluenceDocument.id)
        .where(
            ConfluenceDocument.validation_status.in_(
                (ValidationStatus.PASSED, ValidationStatus.FAILED)
            ),
            or_(
                rating_sq.c.ratings_count.is_(None),
                rating_sq.c.ratings_count == 0,
                rating_sq.c.last_rated_at < ValidationReport.created_at,
            ),
        )
        .order_by(ValidationReport.created_at.desc())
    )
    if lead_user_id is not None:
        lead_sq = select(Analyst.id).where(Analyst.lead_user_id == lead_user_id)
        query = query.where(ConfluenceDocument.analyst_id.in_(lead_sq))
    return query


def _latest_reports(db: Session, document_ids: list[int]) -> dict[int, ValidationReport]:
    """Последние отчёты документов одним запросом (без N+1)."""
    if not document_ids:
        return {}
    latest_sq = (
        select(
            ValidationReport.document_id,
            func.max(ValidationReport.id).label("report_id"),
        )
        .where(ValidationReport.document_id.in_(document_ids))
        .group_by(ValidationReport.document_id)
        .subquery()
    )
    reports = db.execute(
        select(ValidationReport).join(
            latest_sq, ValidationReport.id == latest_sq.c.report_id
        )
    ).scalars().all()
    return {report.document_id: report for report in reports}


def _count_docs(db: Session, *conditions) -> int:
    return db.scalar(
        select(func.count()).select_from(ConfluenceDocument).where(*conditions)
    ) or 0
