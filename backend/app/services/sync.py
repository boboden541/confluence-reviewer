"""Синхронизация страниц Confluence по аналитикам (ФТ-CR-3..ФТ-CR-6).

Полное содержимое (body.storage) догружается только для новых или
изменившихся страниц — экономим запросы к API (НФТ-CR-6).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select

from app.config import get_settings
from app.clients.confluence import ConfluenceClient, ConfluenceError, PageSummary, creator_candidates
from app.database import SessionLocal
from app.models import Analyst, ConfluenceDocument, ValidationStatus
from app.utils import now_utc

logger = logging.getLogger("confluence_reviewer.sync")


@dataclass
class SyncResult:
    analyst_id: int
    analyst_name: str
    created: int = 0
    updated: int = 0
    error: str | None = None
    details: list[str] = field(default_factory=list)


def _needs_content_refresh(doc: ConfluenceDocument | None, summary: PageSummary) -> bool:
    """Полное содержимое нужно, если документ новый/пустой или страница менялась."""
    if doc is None or not doc.content_html:
        return True
    if summary.last_modified_at is None:
        return False
    if doc.last_modified_in_confluence_at is None:
        return True
    return summary.last_modified_at > doc.last_modified_in_confluence_at


async def _find_pages(client: ConfluenceClient, analyst: Analyst) -> list[PageSummary]:
    """Поиск страниц: перебираем кандидатов creator (email -> username, ФТ 3.1 №13).

    Ошибки API не глотаем: любая пробрасывается и фиксируется как sync_error.
    """
    settings = get_settings()
    candidates = creator_candidates(
        analyst.email, analyst.confluence_username, settings.confluence_creator_field
    )
    for candidate in candidates:
        pages = await client.search_pages(candidate)
        if pages:
            logger.info("creator=%s: найдено страниц — %d", candidate, len(pages))
            return pages
    return []


async def sync_analyst(analyst_id: int) -> SyncResult:
    """Актуализировать список страниц одного аналитика (ФТ-CR-3, ФТ-CR-6)."""
    settings = get_settings()
    with SessionLocal() as db:
        analyst = db.get(Analyst, analyst_id)
        if analyst is None:
            return SyncResult(analyst_id=analyst_id, analyst_name="?", error="Аналитик не найден")

        result = SyncResult(analyst_id=analyst.id, analyst_name=analyst.full_name)
        try:
            async with ConfluenceClient(settings) as client:
                summaries = await _find_pages(client, analyst)
                for summary in summaries:
                    try:
                        doc = db.scalar(
                            select(ConfluenceDocument).where(
                                ConfluenceDocument.confluence_page_id == summary.page_id
                            )
                        )
                        is_new = doc is None
                        if is_new:
                            doc = ConfluenceDocument(
                                confluence_page_id=summary.page_id,
                                analyst_id=analyst.id,
                                title=summary.title,
                                url=summary.url,
                            )
                            db.add(doc)

                        content = None
                        if _needs_content_refresh(doc, summary):
                            content = await client.get_page(summary.page_id)

                        doc.title = summary.title
                        doc.url = summary.url
                        doc.last_synced_at = now_utc()
                        doc.sync_error = None
                        if content is not None:
                            doc.content_html = content.content_html
                            doc.created_in_confluence_at = content.created_at or doc.created_in_confluence_at
                            doc.last_modified_in_confluence_at = (
                                content.last_modified_at or summary.last_modified_at
                            )
                            if not is_new:
                                # Страница изменилась после прошлой проверки —
                                # статус сбрасываем, отчёт устарел (замечание №3)
                                doc.validation_status = ValidationStatus.NOT_CHECKED
                                doc.last_validated_at = None
                        else:
                            doc.created_in_confluence_at = (
                                summary.created_at or doc.created_in_confluence_at
                            )
                            doc.last_modified_in_confluence_at = (
                                doc.last_modified_in_confluence_at or summary.last_modified_at
                            )

                        if is_new:
                            result.created += 1
                        else:
                            result.updated += 1
                    except ConfluenceError as exc:
                        result.details.append(f"Страница {summary.page_id}: {exc}")
                        logger.warning("Ошибка загрузки страницы %s: %s", summary.page_id, exc)

            analyst.last_synced_at = now_utc()
            analyst.sync_error = "; ".join(result.details) or None
            db.commit()
        except ConfluenceError as exc:
            analyst.sync_error = str(exc)
            db.commit()
            result.error = str(exc)
            logger.error("Синхронизация %s не удалась: %s", analyst.email, exc)

    return result


async def sync_all() -> list[SyncResult]:
    """Синхронизация всех аналитиков (ФТ-CR-5)."""
    with SessionLocal() as db:
        ids = db.scalars(select(Analyst.id).order_by(Analyst.id)).all()
    results: list[SyncResult] = []
    for analyst_id in ids:
        results.append(await sync_analyst(analyst_id))
    return results
