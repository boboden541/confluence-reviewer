"""Публикация замечаний отчёта комментарием на страницу Confluence (ФТ-CR-17).

Комментарий собирается из последнего отчёта валидации документа и
публикуется через Confluence REST API. Отчёт запоминает момент отправки,
чтобы не дублировать комментарий повторной кнопкой.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app import repository
from app.config import get_settings
from app.clients.confluence import ConfluenceClient
from app.models import ConfluenceDocument, ValidationReport
from app.usecase.exceptions import CommentError, DocumentNotFound, NoReportError
from app.utils import now_utc

logger = logging.getLogger("confluence_reviewer.comments")


def build_comment(report: ValidationReport, document: ConfluenceDocument) -> str:
    """Текст комментария по отчёту (plain text, HTML экранируется клиентом)."""
    lines: list[str] = []
    lines.append(f"🔍 Автоматическая проверка требований «{document.title}»")
    lines.append("")
    lines.append(f"Отчёт от {report.created_at:%d.%m.%Y %H:%M} UTC (запуск: {_trigger(report.triggered_by)}).")
    lines.append("")

    # блок шаблона — только если проверка запускалась (NULL = не запускалась)
    if report.template_passed is not None:
        lines.append(("✅" if report.template_passed else "❌") + " Соответствие шаблону требований: "
                     + ("пройдено" if report.template_passed else "не пройдено"))
        if report.template_findings:
            lines.append(report.template_findings)
        lines.append("")

    if report.ai_passed is not None:
        lines.append(("✅" if report.ai_passed else "❌") + " Качество содержимого (ИИ-проверка): "
                     + ("пройдено" if report.ai_passed else "не пройдено"))
        if report.ai_findings:
            lines.append(report.ai_findings)
        lines.append("")

    lines.append("— Confluence Reviewer")
    return "\n".join(lines)


def _trigger(value) -> str:
    return "автоматический" if getattr(value, "value", value) == "auto" else "ручной"


async def publish_report_comment(db: Session, document_id: int) -> ValidationReport:
    """Опубликовать замечания последнего отчёта (ФТ-CR-17).

    Работает по сессии запроса: чтение документа и отчёта, HTTP-вызов в
    Confluence, затем отметка об отправке в той же сессии. Возвращает
    обновлённый отчёт с проставленным comment_sent_at.
    """
    document = db.get(ConfluenceDocument, document_id)
    if document is None:
        raise DocumentNotFound(f"Документ {document_id} не найден")
    report = repository.reports.get_latest(db, document_id)
    if report is None:
        raise NoReportError(f"У документа {document_id} нет отчёта валидации")
    if report.error_message:
        raise CommentError("Отчёт содержит техническую ошибку — опубликуйте после успешной проверки")
    if report.comment_sent_at is not None:
        raise CommentError("Комментарий по этому отчёту уже опубликован")
    page_id = document.confluence_page_id
    text = build_comment(report, document)

    settings = get_settings()
    async with ConfluenceClient(settings) as client:
        await client.add_comment(page_id, text)

    report.comment_sent_at = now_utc()
    db.commit()
    db.refresh(report)
    logger.info("Комментарий по отчёту %s опубликован на странице %s", report.id, page_id)
    return report


__all__ = [
    "NoReportError",
    "CommentError",
    "build_comment",
    "publish_report_comment",
]
