"""Напоминания: личный список «вернуться к аналитику/документу»."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.dependencies.auth import require_user, resolve_actor
from app.models import Analyst, ConfluenceDocument, Reminder, User
from app.schemas.reminders import ReminderCreate, ReminderOut
from app.usecase import reminders as reminders_uc
from app.usecase.exceptions import AnalystNotFound

router = APIRouter(prefix="/api/reminders", tags=["reminders"])


def _out(db: Session, reminder: Reminder) -> ReminderOut:
    analyst = db.get(Analyst, reminder.analyst_id)
    document = (
        db.get(ConfluenceDocument, reminder.document_id)
        if reminder.document_id is not None
        else None
    )
    return ReminderOut(
        id=reminder.id,
        analyst_id=reminder.analyst_id,
        analyst_name=analyst.full_name if analyst else "?",
        document_id=reminder.document_id,
        document_title=document.title if document else None,
        text=reminder.text,
        remind_at=reminder.remind_at,
        done_at=reminder.done_at,
        created_at=reminder.created_at,
        status="done" if reminder.done_at is not None else "open",
        group=reminders_uc.group_of(reminder),
    )


def _actor(db: Session, user: User | None) -> User:
    return resolve_actor(db, user)


def _own(db: Session, user: User | None, reminder_id: int) -> Reminder:
    actor = resolve_actor(db, user)
    try:
        return reminders_uc.get_own(db, actor, reminder_id)
    except reminders_uc.ReminderNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("", response_model=list[ReminderOut])
def list_reminders(
    analyst_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    """Свои напоминания: открытые по дате «вернуться», затем выполненные."""
    return [_out(db, r) for r in reminders_uc.list_for_user(db, _actor(db, user), analyst_id=analyst_id)]


@router.post("", response_model=ReminderOut, status_code=status.HTTP_201_CREATED)
def create_reminder(
    payload: ReminderCreate,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    try:
        reminder = reminders_uc.create(
            db,
            user=_actor(db, user),
            analyst_id=payload.analyst_id,
            document_id=payload.document_id,
            text=payload.text,
            remind_at=payload.remind_at,
        )
    except AnalystNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except reminders_uc.ReminderDocumentMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _out(db, reminder)


@router.post("/{reminder_id}/done", response_model=ReminderOut)
def mark_done(
    reminder_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    reminder = _own(db, user, reminder_id)
    return _out(db, reminders_uc.mark_done(db, _actor(db, user), reminder_id))


@router.post("/{reminder_id}/reopen", response_model=ReminderOut)
def reopen(
    reminder_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    reminder = _own(db, user, reminder_id)
    return _out(db, reminders_uc.reopen(db, _actor(db, user), reminder_id))


@router.delete("/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reminder(
    reminder_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    _own(db, user, reminder_id)
    try:
        reminders_uc.delete(db, _actor(db, user), reminder_id)
    except reminders_uc.ReminderNotDone as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Удалить можно только выполненное напоминание",
        ) from exc
