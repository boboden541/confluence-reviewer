"""Реестр аналитиков: список и создание карточек (ФТ-CR-1, ФТ-CR-2)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models import (
    AiCriterion,
    Analyst,
    AnalystNote,
    ConfluenceDocument,
    CriterionRating,
)
from app.schemas import (
    AnalystCreate,
    AnalystNoteOut,
    AnalystNoteUpdate,
    AnalystOut,
    AnalystUpdate,
    CriterionSummaryOut,
    RatingsSummaryOut,
)
from app.utils import normalize_period_end, to_naive_utc

router = APIRouter(prefix="/api/analysts", tags=["analysts"])


def get_analyst_or_404(analyst_id: int, db: Session) -> Analyst:
    analyst = db.get(Analyst, analyst_id)
    if analyst is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Аналитик не найден")
    return analyst


def _get_note(db: Session, analyst_id: int) -> AnalystNote | None:
    return db.scalar(select(AnalystNote).where(AnalystNote.analyst_id == analyst_id))


@router.get("", response_model=list[AnalystOut])
def list_analysts(db: Session = Depends(get_db)):
    """ФТ-CR-2: список всех аналитиков с ФИО, email и числом документов."""
    count_sq = (
        select(ConfluenceDocument.analyst_id, func.count().label("cnt"))
        .group_by(ConfluenceDocument.analyst_id)
        .subquery()
    )
    rows = db.execute(
        select(Analyst, func.coalesce(count_sq.c.cnt, 0).label("documents_count"))
        .outerjoin(count_sq, count_sq.c.analyst_id == Analyst.id)
        .order_by(Analyst.full_name)
    ).all()
    result = []
    for analyst, count in rows:
        item = AnalystOut.model_validate(analyst)
        item.documents_count = count
        result.append(item)
    return result


@router.post("", response_model=AnalystOut, status_code=status.HTTP_201_CREATED)
def create_analyst(payload: AnalystCreate, db: Session = Depends(get_db)):
    """ФТ-CR-1: создание карточки аналитика."""
    exists = db.scalar(select(Analyst).where(Analyst.email == payload.email))
    if exists is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Аналитик с email {payload.email} уже существует",
        )
    analyst = Analyst(
        full_name=payload.full_name.strip(),
        email=payload.email.lower(),
        confluence_username=payload.confluence_username,
    )
    db.add(analyst)
    db.commit()
    db.refresh(analyst)
    return AnalystOut.model_validate(analyst)


@router.get("/{analyst_id}", response_model=AnalystOut)
def get_analyst(analyst_id: int, db: Session = Depends(get_db)):
    analyst = get_analyst_or_404(analyst_id, db)
    count = db.scalar(
        select(func.count()).select_from(ConfluenceDocument).where(
            ConfluenceDocument.analyst_id == analyst.id
        )
    )
    item = AnalystOut.model_validate(analyst)
    item.documents_count = count or 0
    return item


@router.put("/{analyst_id}", response_model=AnalystOut)
def update_analyst(analyst_id: int, payload: AnalystUpdate, db: Session = Depends(get_db)):
    """Редактирование карточки аналитика (ФИО, email, username в Confluence)."""
    analyst = get_analyst_or_404(analyst_id, db)
    duplicate = db.scalar(
        select(Analyst).where(Analyst.email == payload.email, Analyst.id != analyst_id)
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Аналитик с email {payload.email} уже существует",
        )
    analyst.full_name = payload.full_name.strip()
    analyst.email = payload.email.lower()
    analyst.confluence_username = payload.confluence_username
    db.commit()
    db.refresh(analyst)
    item = AnalystOut.model_validate(analyst)
    item.documents_count = (
        db.scalar(
            select(func.count()).select_from(ConfluenceDocument).where(
                ConfluenceDocument.analyst_id == analyst.id
            )
        )
        or 0
    )
    return item


@router.delete("/{analyst_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_analyst(analyst_id: int, db: Session = Depends(get_db)):
    """Удалить аналитика вместе с его документами, отчётами и заметками."""
    analyst = get_analyst_or_404(analyst_id, db)
    db.delete(analyst)  # каскад: документы → отчёты и заметки
    db.commit()


@router.get("/{analyst_id}/note", response_model=AnalystNoteOut)
def get_analyst_note(analyst_id: int, db: Session = Depends(get_db)):
    """Заметка по аналитику в его профиле; пустая, если ещё не было."""
    get_analyst_or_404(analyst_id, db)
    note = _get_note(db, analyst_id)
    if note is None:
        return AnalystNoteOut(analyst_id=analyst_id, content="")
    return AnalystNoteOut.model_validate(note)


@router.put("/{analyst_id}/note", response_model=AnalystNoteOut)
def update_analyst_note(
    analyst_id: int, payload: AnalystNoteUpdate, db: Session = Depends(get_db)
):
    """Создать или перезаписать заметку (Markdown, одна на аналитика)."""
    get_analyst_or_404(analyst_id, db)
    note = _get_note(db, analyst_id)
    if note is None:
        note = AnalystNote(analyst_id=analyst_id, content=payload.content)
        db.add(note)
    else:
        note.content = payload.content
    db.commit()
    db.refresh(note)
    return AnalystNoteOut.model_validate(note)


@router.delete("/{analyst_id}/note", status_code=status.HTTP_204_NO_CONTENT)
def delete_analyst_note(analyst_id: int, db: Session = Depends(get_db)):
    """Удалить заметку аналитика. Идемпотентно: заметки нет — тоже 204."""
    get_analyst_or_404(analyst_id, db)
    note = _get_note(db, analyst_id)
    if note is not None:
        db.delete(note)
        db.commit()


@router.get("/{analyst_id}/ratings-summary", response_model=RatingsSummaryOut)
def get_ratings_summary(
    analyst_id: int,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    db: Session = Depends(get_db),
):
    """Средние оценки руководителя по ИИ-критериям аналитика за период.

    Период отсчитывается по дате создания документа в Confluence
    (created_in_confluence_at): руководитель смотрит, как аналитик работал
    в выбранный период, не таща ретроспективу; дата выставления самой
    оценки не важна. По умолчанию — все документы. Границы включительны
    (date-only «по» охватывает весь последний день); документы без даты
    создания в период не попадают. Снятые оценки («—») записями не являются
    и в статистику не попадают. Сортировка критериев: от сильных к слабым.
    """
    analyst = get_analyst_or_404(analyst_id, db)
    # aware-границы («Z», «+03:00») приводим к наивному UTC до guard и SQL:
    # иначе сравнение naive>aware даёт 500, а SQL теряет offset
    date_from = to_naive_utc(date_from)
    date_to = to_naive_utc(date_to)
    if date_from is not None and date_to is not None and date_from > normalize_period_end(date_to):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Дата начала периода позже даты окончания",
        )

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
        .where(ConfluenceDocument.analyst_id == analyst.id)
        .group_by(AiCriterion.id, AiCriterion.code, AiCriterion.name, AiCriterion.is_archived)
    )
    if date_from is not None:
        query = query.where(ConfluenceDocument.created_in_confluence_at >= date_from)
    if date_to is not None:
        query = query.where(
            ConfluenceDocument.created_in_confluence_at <= normalize_period_end(date_to)
        )
    rows = db.execute(query).all()

    criteria = [
        CriterionSummaryOut(
            criterion_id=row.id,
            code=row.code,
            name=row.name,
            is_archived=row.is_archived,
            average=round(row.average, 2),
            ratings_count=row.ratings_count,
        )
        for row in rows
    ]
    criteria.sort(key=lambda c: (-c.average, c.name.lower()))

    total = sum(c.ratings_count for c in criteria)
    overall = (
        round(sum(c.average * c.ratings_count for c in criteria) / total, 2) if total else None
    )
    return RatingsSummaryOut(
        analyst_id=analyst.id,
        date_from=date_from,
        # эхо — эффективная граница: ответ честно описывает применённый фильтр
        date_to=normalize_period_end(date_to) if date_to is not None else None,
        overall_average=overall,
        total_ratings=total,
        criteria=criteria,
    )


@router.post("/{analyst_id}/sync", status_code=status.HTTP_202_ACCEPTED, tags=["sync"])
async def trigger_analyst_sync(analyst_id: int, db: Session = Depends(get_db)):
    """ФТ-CR-6: ручной запуск парсинга всех страниц аналитика."""
    get_analyst_or_404(analyst_id, db)
    from app.services import tasks

    started, message = tasks.start_sync(analyst_id)
    if not started:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return {"status": "started", "message": message}


@router.post("/{analyst_id}/validate-all", status_code=status.HTTP_202_ACCEPTED)
async def validate_all_documents(analyst_id: int, db: Session = Depends(get_db)):
    """Ручная массовая проверка документов аналитика (в фоне, последовательно).

    Не-force: актуальные документы пропускаются, проверяются только новые
    и изменившиеся после прошлой проверки.
    """
    get_analyst_or_404(analyst_id, db)
    from app.services import tasks

    started, message = tasks.start_analyst_bulk_validation(analyst_id)
    if not started:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return {"status": "started", "message": message}
