"""Первичное наполнение карточек аналитиков из SEED_ANALYSTS."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Analyst

logger = logging.getLogger("confluence_reviewer")


def parse_seed_line(line: str) -> tuple[str, str] | None:
    """'ФИО:email' -> (ФИО, email); некорректные строки пропускаются."""
    if ":" not in line:
        return None
    full_name, _, email = line.partition(":")
    full_name, email = full_name.strip(), email.strip()
    if not full_name or "@" not in email:
        return None
    return full_name, email


def seed_analysts(db: Session, raw: str) -> int:
    """Создаёт отсутствующие карточки. Возвращает число созданных.

    Сессию открывает вызывающий оркестратор (lifespan держит одну сессию
    на оба сида — аналитики и шаблон требований).
    """
    created = 0
    for line in raw.split(";"):
        parsed = parse_seed_line(line.strip())
        if parsed is None:
            continue
        full_name, email = parsed
        exists = db.scalar(select(Analyst).where(Analyst.email == email))
        if exists:
            continue
        db.add(Analyst(full_name=full_name, email=email))
        created += 1
    db.commit()
    if created:
        logger.info("Seed: добавлено аналитиков — %d", created)
    return created
