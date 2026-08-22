"""Реестр аналитиков: список и создание карточек (ФТ-CR-1, ФТ-CR-2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Analyst, ConfluenceDocument
from app.schemas import AnalystCreate, AnalystOut

router = APIRouter(prefix="/api/analysts", tags=["analysts"])


def get_analyst_or_404(analyst_id: int, db: Session) -> Analyst:
    analyst = db.get(Analyst, analyst_id)
    if analyst is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Аналитик не найден")
    return analyst


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

    started, message = tasks.start_bulk_validation(analyst_id)
    if not started:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return {"status": "started", "message": message}
