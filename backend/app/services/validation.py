"""Оркестрация валидации документа: шаблон + ИИ (ФТ-CR-12..ФТ-CR-16).

Последовательность: статус in_progress → проверка шаблона (скрипт) →
ИИ-проверка содержимого → итоговый отчёт и статус passed/failed.
Технический сбой → статус error и отчёт с текстом ошибки (last_validated_at
не обновляется — повторный запуск повторит попытку).

Идемпотентность (ФТ-CR-14): если документ не менялся в Confluence после
последней успешной валидации, возвращается существующий отчёт без
повторного вызова ИИ. force=true принуждает к перевалидации.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    ConfluenceDocument,
    TriggerType,
    ValidationReport,
    ValidationStatus,
)
from app.services.ai_validator import AIValidationError, AIValidator
from app.services.html_to_markdown import html_to_markdown
from app.services.template_validator import validate_template
from app.utils import now_utc

logger = logging.getLogger("confluence_reviewer.validation")


class DocumentNotFound(LookupError):
    """Документ не существует."""


def _latest_report(db, document_id: int) -> ValidationReport | None:
    return db.scalar(
        select(ValidationReport)
        .where(ValidationReport.document_id == document_id)
        .order_by(ValidationReport.created_at.desc(), ValidationReport.id.desc())
    )


def latest_report(document_id: int) -> ValidationReport | None:
    """Последний отчёт валидации документа (для API)."""
    with SessionLocal() as db:
        return _latest_report(db, document_id)


def _is_up_to_date(doc: ConfluenceDocument) -> bool:
    """Документ не менялся в Confluence с момента последней валидации."""
    return (
        doc.last_validated_at is not None
        and doc.last_modified_in_confluence_at is not None
        and doc.last_validated_at >= doc.last_modified_in_confluence_at
    )


def _save_error(db, doc: ConfluenceDocument, trigger: TriggerType, message: str) -> ValidationReport:
    """ФТ-CR-15: технический сбой → статус error, текст ошибки в отчёте."""
    report = ValidationReport(document_id=doc.id, triggered_by=trigger, error_message=message)
    db.add(report)
    doc.validation_status = ValidationStatus.ERROR
    db.commit()
    db.refresh(report)
    logger.error("Валидация документа %s завершилась ошибкой: %s", doc.id, message)
    return report


def run_validation(
    document_id: int,
    *,
    trigger: TriggerType = TriggerType.MANUAL,
    force: bool = False,
) -> ValidationReport:
    """Прогнать проверки документа и сохранить отчёт."""
    with SessionLocal() as db:
        doc = db.get(ConfluenceDocument, document_id)
        if doc is None:
            raise DocumentNotFound(f"Документ {document_id} не найден")

        existing = _latest_report(db, doc.id)
        if (
            not force
            and existing is not None
            and existing.error_message is None
            and _is_up_to_date(doc)
        ):
            return existing  # ФТ-CR-14: ничего не изменилось — отчёт актуален

        doc.validation_status = ValidationStatus.IN_PROGRESS
        db.commit()

        try:
            template_result = validate_template(doc.title, doc.content_html)
        except Exception as exc:  # noqa: BLE001 — любая ошибка = статус error
            return _save_error(db, doc, trigger, f"Ошибка проверки шаблона: {exc}")

        try:
            markdown = html_to_markdown(doc.content_html)
            ai_result = AIValidator().validate(doc.title, markdown)
        except AIValidationError as exc:
            return _save_error(db, doc, trigger, str(exc))

        overall = template_result.passed and ai_result.passed
        report = ValidationReport(
            document_id=doc.id,
            triggered_by=trigger,
            template_passed=template_result.passed,
            template_findings=template_result.findings_markdown,
            ai_passed=ai_result.passed,
            ai_findings=ai_result.findings_markdown,
            overall_passed=overall,
        )
        db.add(report)
        doc.validation_status = ValidationStatus.PASSED if overall else ValidationStatus.FAILED
        doc.last_validated_at = now_utc()
        db.commit()
        db.refresh(report)
        return report
