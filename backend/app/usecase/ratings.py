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

from sqlalchemy.orm import Session

from app import repository
from app.models import CriterionRating
from app.schemas import RatingItem, RatingItemOut, RatingsOut
from app.usecase.criteria import select_criteria
from app.usecase.exceptions import CriterionNotFound


def get_ratings_view(db: Session, document_id: int, owner_user=None) -> RatingsOut:
    """Активные критерии пользователя (тот, кто смотрит документ — он и
    оценивает) с его оценками; порядок — справочника. owner_user=None —
    авторизация выключена, без фильтра."""
    owner_user_id = owner_user.id if owner_user is not None else None
    criteria = select_criteria(db, owner_user_id=owner_user_id)
    report = repository.reports.get_latest(db, document_id)
    ratings = {
        rating.criterion_id: rating
        for rating in repository.ratings.list_for_document(db, document_id)
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


def apply_ratings(
    db: Session, document_id: int, items: list[RatingItem], owner_user=None
) -> RatingsOut:
    """Upsert оценок: score=None удаляет запись (идемпотентно). Оценивать
    можно только свои критерии (чужой id — 404)."""
    owner_user_id = owner_user.id if owner_user is not None else None
    # валидация набора — единый паттерн с прогоном (usecase.criteria):
    # несуществующий/архивный критерий — ошибка, молча вычеркивать нельзя
    try:
        select_criteria(db, [item.criterion_id for item in items], owner_user_id=owner_user_id)
    except LookupError as exc:
        raise CriterionNotFound(str(exc)) from exc

    for item in items:
        rating = repository.ratings.get(db, document_id, item.criterion_id)
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
