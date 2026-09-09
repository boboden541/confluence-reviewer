"""Личные напоминания: создание, список, статусная модель.

Строго личные: любая операция проверяет владельца, чужое — 404 (не 403,
чтобы не раскрывать существование чужих напоминаний).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Analyst, ConfluenceDocument, Reminder, User
from app.usecase.exceptions import AnalystNotFound
from app.utils import to_naive_utc


class ReminderNotFound(Exception):
    """Напоминание не существует или принадлежит другому пользователю."""


class ReminderDocumentMismatch(Exception):
    """Документ не принадлежит выбранному аналитику."""


class ReminderNotDone(Exception):
    """Удалить можно только выполненное напоминание."""


def _get_own(db: Session, user: User, reminder_id: int) -> Reminder:
    reminder = db.get(Reminder, reminder_id)
    if reminder is None or reminder.user_id != user.id:
        raise ReminderNotFound("Напоминание не найдено")
    return reminder


def create(
    db: Session,
    *,
    user: User,
    analyst_id: int,
    document_id: int | None,
    text: str,
    remind_at: datetime | None,
) -> Reminder:
    analyst = db.get(Analyst, analyst_id)
    if analyst is None:
        raise AnalystNotFound(f"Аналитик {analyst_id} не найден")
    document: ConfluenceDocument | None = None
    if document_id is not None:
        document = db.get(ConfluenceDocument, document_id)
        if document is None or document.analyst_id != analyst_id:
            raise ReminderDocumentMismatch("Документ не принадлежит выбранному аналитику")
    reminder = Reminder(
        user_id=user.id,
        analyst_id=analyst_id,
        document_id=document_id,
        text=text.strip(),
        remind_at=to_naive_utc(remind_at),
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return reminder


def list_for_user(
    db: Session, user: User, *, analyst_id: int | None = None
) -> list[Reminder]:
    """Свои напоминания: открытые (по дате «вернуться», NULL — в конец),
    затем выполненные (свежие сверху)."""
    conditions = [Reminder.user_id == user.id]
    if analyst_id is not None:
        conditions.append(Reminder.analyst_id == analyst_id)
    return list(
        db.scalars(
            select(Reminder)
            .where(*conditions)
            .order_by(
                Reminder.done_at.is_not(None),
                Reminder.remind_at.is_(None),
                Reminder.remind_at.asc(),
                Reminder.done_at.desc().nullslast(),
            )
        ).all()
    )


def mark_done(db: Session, user: User, reminder_id: int) -> Reminder:
    reminder = _get_own(db, user, reminder_id)
    if reminder.done_at is None:
        reminder.done_at = datetime.utcnow()
        db.commit()
        db.refresh(reminder)
    return reminder


def reopen(db: Session, user: User, reminder_id: int) -> Reminder:
    reminder = _get_own(db, user, reminder_id)
    if reminder.done_at is not None:
        reminder.done_at = None
        db.commit()
        db.refresh(reminder)
    return reminder


def delete(db: Session, user: User, reminder_id: int) -> None:
    reminder = _get_own(db, user, reminder_id)
    if reminder.done_at is None:
        raise ReminderNotDone("Удалить можно только выполненное напоминание")
    db.delete(reminder)
    db.commit()
