"""Оценки руководителя по ИИ-критериям документа (1..10 и «—»).

Блок оценивания строится по всем активным критериям справочника —
независимо от прогонов: руководитель оценивает документ по каждому
заведённому критерию, даже если последний прогон шёл по узкому набору
или документа ещё не касался ИИ. Архивные критерии из блока скрыты
(их прошлые оценки живут в БД и статистике). Записи оценок переживают
новые прогоны: актуальность каждой показывает stale (оценка выставлена
до created_at текущего отчёта).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CriterionRating
from app.schemas import RatingItem, RatingItemOut, RatingsOut
from app.usecase.criteria import select_criteria
from app.services.validation import _latest_report


class CriterionNotFound(LookupError):
    """Критерий из запроса не существует или в архиве (оценить нельзя)."""


def get_ratings_view(db: Session, document_id: int) -> RatingsOut:
    """Все активные критерии справочника с оценками; порядок — справочника."""
    criteria = select_criteria(db)
    report = _latest_report(db, document_id)
    ratings = {
        rating.criterion_id: rating
        for rating in db.scalars(
            select(CriterionRating).where(CriterionRating.document_id == document_id)
        ).all()
    }

    items: list[RatingItemOut] = []
    for criterion in criteria:
        rating = ratings.get(criterion.id)
        items.append(
            RatingItemOut(
                criterion_id=criterion.id,
                code=criterion.code,
                name=criterion.name,
                is_archived=criterion.is_archived,  # всегда False: взяли активные
                score=rating.score if rating else None,
                updated_at=rating.updated_at if rating else None,
                stale=bool(rating)
                and report is not None
                and rating.updated_at < report.created_at,
            )
        )
    return RatingsOut(document_id=document_id, criteria=items)


def apply_ratings(db: Session, document_id: int, items: list[RatingItem]) -> RatingsOut:
    """Upsert оценок: score=None удаляет запись (идемпотентно)."""
    # валидация набора — единый паттерн с прогоном (services.criteria):
    # несуществующий/архивный критерий — ошибка, молча вычеркивать нельзя
    try:
        select_criteria(db, [item.criterion_id for item in items])
    except LookupError as exc:
        raise CriterionNotFound(str(exc)) from exc

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

    # после применения блок переосмысливается целиком: оценки, stale-флаги,
    # критерии, ушедшие в архив после выставления
    return get_ratings_view(db, document_id)
