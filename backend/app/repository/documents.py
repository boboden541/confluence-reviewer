"""Выборки документов аналитиков."""

from __future__ import annotations

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.models import Analyst, ConfluenceDocument, DocumentNote


def _page_conditions(
    analyst_id: int,
    title: str | None,
    url: str | None,
    created_from,
    created_to,
) -> list[ColumnElement[bool]]:
    """WHERE списка документов; title/url — уже нормализованы usecase'ом."""
    conditions: list[ColumnElement[bool]] = [ConfluenceDocument.analyst_id == analyst_id]
    if title:
        # lower() с обеих сторон: sqlite ILIKE не сворачивает регистр кириллицы
        conditions.append(func.lower(ConfluenceDocument.title).like(f"%{title}%"))
    if url:
        conditions.append(func.lower(ConfluenceDocument.url).like(f"%{url}%"))
    if created_from is not None:
        conditions.append(ConfluenceDocument.created_in_confluence_at >= created_from)
    if created_to is not None:
        conditions.append(ConfluenceDocument.created_in_confluence_at <= created_to)
    return conditions


def page_list(
    db: Session,
    analyst_id: int,
    *,
    title: str | None = None,
    url: str | None = None,
    created_from=None,
    created_to=None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ConfluenceDocument], int]:
    """Страница списка (новые сверху) и общее число документов фильтра."""
    conditions = _page_conditions(analyst_id, title, url, created_from, created_to)
    total = db.scalar(select(func.count()).select_from(ConfluenceDocument).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(ConfluenceDocument)
            .where(*conditions)
            .order_by(
                ConfluenceDocument.created_in_confluence_at.desc().nullslast(),
                ConfluenceDocument.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, total


def noted_ids(db: Session, document_ids: list[int]) -> set[int]:
    """id документов из списка, у которых есть заметка (одним запросом)."""
    if not document_ids:
        return set()
    return set(
        db.scalars(
            select(DocumentNote.document_id).where(DocumentNote.document_id.in_(document_ids))
        ).all()
    )


def semantic_candidates(db: Session, analyst_id: int) -> list[tuple[int, str]]:
    """Кандидаты семантического поиска: (id, заголовок) документов аналитика."""
    return list(
        db.execute(
            select(ConfluenceDocument.id, ConfluenceDocument.title)
            .where(ConfluenceDocument.analyst_id == analyst_id)
            .order_by(ConfluenceDocument.id)
        ).all()
    )


def fetch_by_ids(db: Session, document_ids: list[int]) -> list[ConfluenceDocument]:
    """Документы по набору id (порядок не гарантирован)."""
    if not document_ids:
        return []
    return list(
        db.scalars(
            select(ConfluenceDocument).where(ConfluenceDocument.id.in_(document_ids))
        ).all()
    )


def existing_ids(db: Session, document_ids: list[int]) -> set[int]:
    """Какие из перечисленных id реально есть в БД."""
    if not document_ids:
        return set()
    return set(
        db.scalars(
            select(ConfluenceDocument.id).where(ConfluenceDocument.id.in_(document_ids))
        ).all()
    )


def global_search(db: Session, needle: str, limit: int) -> list[tuple[ConfluenceDocument, str]]:
    """Глобальный поиск по подстроке названия: (документ, ФИО аналитика)."""
    return list(
        db.execute(
            select(ConfluenceDocument, Analyst.full_name)
            .join(Analyst, ConfluenceDocument.analyst_id == Analyst.id)
            .where(func.lower(ConfluenceDocument.title).like(f"%{needle}%"))
            .order_by(
                ConfluenceDocument.last_modified_in_confluence_at.desc().nullslast(),
                ConfluenceDocument.id.desc(),
            )
            .limit(limit)
        ).all()
    )


def get_note(db: Session, document_id: int) -> DocumentNote | None:
    """Заметка документа (одна на документ)."""
    return db.scalar(select(DocumentNote).where(DocumentNote.document_id == document_id))


def get_by_page_id(db: Session, page_id: str) -> ConfluenceDocument | None:
    """Документ по id страницы Confluence (поиск при синхронизации)."""
    return db.scalar(
        select(ConfluenceDocument).where(ConfluenceDocument.confluence_page_id == page_id)
    )


def ids_for_analyst(db: Session, analyst_id: int) -> list[int]:
    """id всех документов аналитика по возрастанию (массовая проверка)."""
    return list(
        db.scalars(
            select(ConfluenceDocument.id)
            .where(ConfluenceDocument.analyst_id == analyst_id)
            .order_by(ConfluenceDocument.id)
        ).all()
    )
