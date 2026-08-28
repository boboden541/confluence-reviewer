"""Оценки руководителя по ИИ-критериям документа (1..5 и «—»).

Блок оценивания строится по последнему прогону документа: какие критерии
участвовали (ai_criteria_codes отчёта) — те и оцениваются, в порядке прогона.
Записи оценок переживают новые прогоны: актуальность каждой показывает
stale (оценка выставлена до created_at текущего отчёта).
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AiCriterion, CriterionRating
from app.schemas import RatingItem, RatingItemOut, RatingsOut
from app.services.validation import _latest_report


class CriterionNotFound(LookupError):
    """Критерий из запроса не существует (оценить нельзя)."""


def get_ratings_view(db: Session, document_id: int) -> RatingsOut:
    """Критерии последнего прогона с оценками; порядок — порядок прогона."""
    report = _latest_report(db, document_id)
    if report is None or not report.ai_criteria_codes:
        return RatingsOut(document_id=document_id, criteria=[])

    codes: list[str] = json.loads(report.ai_criteria_codes)
    criteria = {
        criterion.code: criterion
        for criterion in db.scalars(
            select(AiCriterion).where(AiCriterion.code.in_(codes))
        ).all()
    }
    ratings = {
        rating.criterion_id: rating
        for rating in db.scalars(
            select(CriterionRating).where(CriterionRating.document_id == document_id)
        ).all()
    }

    items: list[RatingItemOut] = []
    for code in dict.fromkeys(codes):  # дубликаты схлопываем, порядок сохраняем
        criterion = criteria.get(code)
        if criterion is None:
            continue  # критерий удалён из справочника физически — оценивать нечего
        rating = ratings.get(criterion.id)
        items.append(
            RatingItemOut(
                criterion_id=criterion.id,
                code=criterion.code,
                name=criterion.name,
                is_archived=criterion.is_archived,
                score=rating.score if rating else None,
                updated_at=rating.updated_at if rating else None,
                stale=bool(rating) and rating.updated_at < report.created_at,
            )
        )
    return RatingsOut(document_id=document_id, criteria=items)


def apply_ratings(db: Session, document_id: int, items: list[RatingItem]) -> RatingsOut:
    """Upsert оценок: score=None удаляет запись (идемпотентно)."""
    for item in items:
        if db.get(AiCriterion, item.criterion_id) is None:
            raise CriterionNotFound(f"Критерий {item.criterion_id} не найден")

    for item in items:
        rating = db.scalar(
            select(CriterionRating).where(
                CriterionRating.document_id == document_id,
                CriterionRating.criterion_id == item.criterion_id,
            )
        )
        if item.score is None:
            if rating is not None:  # снятие оценки — «—»; отсутствующая и так «—»
                db.delete(rating)
        elif rating is None:
            db.add(CriterionRating(document_id=document_id, **item.model_dump()))
        else:
            rating.score = item.score
    db.commit()

    # после применения блок переосмысливается целиком: порядок прогона,
    # stale-флаги, критерии, добавленные в справочник после отчёта
    return get_ratings_view(db, document_id)
