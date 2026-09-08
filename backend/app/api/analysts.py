"""Реестр аналитиков: список и создание карточек (ФТ-CR-1, ФТ-CR-2).

Тонкий слой над usecase.analysts: перевод доменных исключений в HTTP-ответы
с теми же кодами и текстами.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_permission, require_user
from app.dependencies.auth import resolve_actor
from app.schemas import (
    AnalystLeadUpdate,
    AnalystLeadUpdate,
    AnalystCreate,
    AnalystDomainsUpdate,
    AnalystNoteOut,
    AnalystNoteUpdate,
    AnalystOut,
    AnalystUpdate,
    RatingsSummaryOut,
)
from app.usecase import auth as auth_uc
from app.usecase import analysts as analysts_uc
from app.usecase import tasks
from app.usecase.exceptions import AnalystEmailTaken, AnalystNotFound
from app.utils import normalize_period_end, to_naive_utc

router = APIRouter(prefix="/api/analysts", tags=["analysts"])


def _get_analyst_or_404(analyst_id: int, db: Session):
    try:
        return analysts_uc.get_analyst(db, analyst_id)
    except AnalystNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Аналитик не найден") from exc


@router.get("", response_model=list[AnalystOut])
def list_analysts(db: Session = Depends(get_db)):
    """ФТ-CR-2: список всех аналитиков с ФИО, email и числом документов."""
    return analysts_uc.list_analysts(db)


@router.post("", response_model=AnalystOut, status_code=status.HTTP_201_CREATED)
def create_analyst(payload: AnalystCreate, db: Session = Depends(get_db)):
    """ФТ-CR-1: создание карточки аналитика."""
    try:
        return analysts_uc.create_analyst(db, payload)
    except AnalystEmailTaken as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Аналитик с email {payload.email} уже существует",
        ) from exc


@router.get("/{analyst_id}", response_model=AnalystOut)
def get_analyst(analyst_id: int, db: Session = Depends(get_db)):
    try:
        return analysts_uc.get_analyst_card(db, analyst_id)
    except AnalystNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Аналитик не найден") from exc


@router.put("/{analyst_id}", response_model=AnalystOut)
def update_analyst(analyst_id: int, payload: AnalystUpdate, db: Session = Depends(get_db)):
    """Редактирование карточки аналитика (ФИО, email, username в Confluence)."""
    try:
        return analysts_uc.update_analyst(db, analyst_id, payload)
    except AnalystNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Аналитик не найден") from exc
    except AnalystEmailTaken as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Аналитик с email {payload.email} уже существует",
        ) from exc


@router.delete("/{analyst_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_analyst(
    analyst_id: int,
    db: Session = Depends(get_db),
    _: User | None = Depends(require_permission("delete")),
):
    """Удалить аналитика вместе с его документами, отчётами и заметками."""
    _get_analyst_or_404(analyst_id, db)
    analysts_uc.delete_analyst(db, analyst_id)


@router.put("/{analyst_id}/lead", response_model=AnalystOut)
def set_analyst_lead(
    analyst_id: int,
    payload: AnalystLeadUpdate,
    db: Session = Depends(get_db),
    _: User | None = Depends(require_permission("lead.assign")),
):
    """Назначить аналитику лида (пользователя с ролью lead); user_id null — снять."""
    if payload.user_id is not None:
        lead_user = auth_uc.get_user(db, payload.user_id)
        if lead_user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден"
            )
    try:
        return analysts_uc.set_lead(db, analyst_id, payload.user_id)
    except AnalystNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Аналитик не найден") from exc


@router.get("/{analyst_id}/note", response_model=AnalystNoteOut)
def get_analyst_note(analyst_id: int, db: Session = Depends(get_db)):
    """Заметка по аналитику в его профиле; пустая, если ещё не было."""
    _get_analyst_or_404(analyst_id, db)
    return analysts_uc.get_note_view(db, analyst_id)


@router.put("/{analyst_id}/note", response_model=AnalystNoteOut)
def update_analyst_note(
    analyst_id: int, payload: AnalystNoteUpdate, db: Session = Depends(get_db)
):
    """Создать или перезаписать заметку (Markdown, одна на аналитика)."""
    _get_analyst_or_404(analyst_id, db)
    return analysts_uc.save_note(db, analyst_id, payload.content)


@router.delete("/{analyst_id}/note", status_code=status.HTTP_204_NO_CONTENT)
def delete_analyst_note(analyst_id: int, db: Session = Depends(get_db)):
    """Удалить заметку аналитика. Идемпотентно: заметки нет — тоже 204."""
    _get_analyst_or_404(analyst_id, db)
    analysts_uc.delete_note(db, analyst_id)


@router.put("/{analyst_id}/domains", response_model=list[str])
def update_analyst_domains(
    analyst_id: int, payload: AnalystDomainsUpdate, db: Session = Depends(get_db)
):
    """Домены аналитика (свободные теги); возвращает применённый список."""
    try:
        return analysts_uc.update_analyst_domains(db, analyst_id, payload)
    except AnalystNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Аналитик не найден") from exc


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
    _get_analyst_or_404(analyst_id, db)
    # aware-границы («Z», «+03:00») приводим к наивному UTC до guard и SQL:
    # иначе сравнение naive>aware даёт 500, а SQL теряет offset
    date_from = to_naive_utc(date_from)
    date_to = to_naive_utc(date_to)
    if date_from is not None and date_to is not None and date_from > normalize_period_end(date_to):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Дата начала периода позже даты окончания",
        )
    return analysts_uc.ratings_summary(db, analyst_id, date_from, date_to)


@router.post("/{analyst_id}/sync", status_code=status.HTTP_202_ACCEPTED, tags=["sync"])
async def trigger_analyst_sync(analyst_id: int, db: Session = Depends(get_db)):
    """ФТ-CR-6: ручной запуск парсинга всех страниц аналитика."""
    _get_analyst_or_404(analyst_id, db)
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
    _get_analyst_or_404(analyst_id, db)
    started, message = tasks.start_analyst_bulk_validation(analyst_id)
    if not started:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return {"status": "started", "message": message}
