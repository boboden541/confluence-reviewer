"""Оркестрация валидации документа: шаблон и/или ИИ (ФТ-CR-12..ФТ-CR-16).

Последовательность: статус in_progress → выбранные проверки (шаблон —
скрипт, содержимое — ИИ) → итоговый отчёт и статус passed/failed. Критерии
задаются на запуск (checks); не запущенная проверка оставляет в отчёте NULL
(«не запускалась»). Технический сбой → статус error и отчёт с текстом ошибки
(last_validated_at не обновляется — повторный запуск повторит попытку).

Идемпотентность (ФТ-CR-14): если документ не менялся в Confluence после
последней успешной валидации, модель ИИ та же и все запрошенные проверки
выполнены в кэшированном отчёте, возвращается существующий отчёт без
повторного вызова ИИ. force=true принуждает к перевалидации.
"""

from __future__ import annotations

import hashlib
import json
import logging

from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    ConfluenceDocument,
    TriggerType,
    ValidationReport,
    ValidationStatus,
)
from app.clients.ai_validator import AIValidationError, AIValidator
from app.usecase.ai_settings import get_ai_connection
from app.usecase.criteria import assemble_prompt, select_criteria, seed_criteria_if_missing
from app.services.html_to_markdown import html_to_markdown
from app.usecase.templates import get_template_for_validation
from app.services.template_validator import validate_template
from app.utils import now_utc

logger = logging.getLogger("confluence_reviewer.validation")

# Критерии проверки: структура по шаблону / содержимое (ИИ)
TEMPLATE_CHECK = "template"
AI_CHECK = "ai"
ALL_CHECKS = (TEMPLATE_CHECK, AI_CHECK)


def normalize_checks(checks: list[str] | None) -> set[str]:
    """None → оба критерия (обратная совместимость запуска без опций).

    Непустой список — как передан; пустой набор невозможен через API
    (422 в схеме), прямой вызов с [] — ошибка программирования.
    """
    result = set(checks) if checks is not None else set(ALL_CHECKS)
    if not result:
        raise ValueError("Должен быть выбран хотя бы один критерий проверки")
    return result


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
    template_version_id: int | None = None,
    ai_prompt: str | None = None,
    checks: list[str] | None = None,
    criterion_ids: list[int] | None = None,
) -> ValidationReport:
    """Прогнать выбранные проверки документа и сохранить отчёт.

    checks — критерии этого запуска: ["template"], ["ai"] или оба (None —
    оба, обратная совместимость). Не запущенная проверка оставляет в отчёте
    NULL («не запускалась»); итог = AND по запущенным проверкам. Последующий
    запуск с большим набором критериев всегда полный: NULL-проверка не
    проходит кэш идемпотентности.

    template_version_id / ai_prompt / criterion_ids — настройки из диалога
    проверки: версия шаблона, override промта и критерии ИИ-проверки этого
    запуска (None — все активные). Промт прогона без override собирается из
    критериев; эффективный промт хэшируется в отчёт — любое отличие (правка
    критерия, override) не проходит кэш идемпотентности и переводит
    документ в перевалидацию.
    """
    requested = normalize_checks(checks)
    run_template, run_ai = TEMPLATE_CHECK in requested, AI_CHECK in requested
    # промт имеет смысл только для запускаемой ИИ-проверки: без неё
    # не применяется и не принуждает к перевалидации
    custom_prompt = ai_prompt if run_ai and ai_prompt and ai_prompt.strip() else None

    with SessionLocal() as db:
        doc = db.get(ConfluenceDocument, document_id)
        if doc is None:
            raise DocumentNotFound(f"Документ {document_id} не найден")

        # критерии прогона нужны до проверки кэша: из них собирается промт,
        # а его хэш входит в условие идемпотентности
        criteria = []
        effective_prompt: str | None = None
        prompt_hash: str | None = None
        if run_ai:
            seed_criteria_if_missing(db)
            try:
                criteria = select_criteria(db, criterion_ids)
            except LookupError as exc:
                return _save_error(db, doc, trigger, str(exc))
            if not criteria:
                return _save_error(
                    db, doc, trigger, "Нет активных ИИ-критериев — добавьте или восстановите"
                )
            assembled = assemble_prompt(criteria)
            # присланный промт дословно равен собранному — это не override
            # (кнопка «вернуть собранный промт» в диалоге отправляет null,
            # но дословное совпадение не должно форсировать перепроверку)
            if custom_prompt is not None and custom_prompt == assembled:
                custom_prompt = None
            effective_prompt = custom_prompt or assembled
            prompt_hash = hashlib.sha256(effective_prompt.encode("utf-8")).hexdigest()

        existing = _latest_report(db, doc.id)
        # эффективное подключение ИИ: env + настройки из UI (по-полё);
        # нужно только для ИИ-проверки (её результат и кэш по модели)
        connection = get_ai_connection(db) if run_ai else None
        if (
            not force
            and existing is not None
            and existing.error_message is None
            and _is_up_to_date(doc)
            # запрошенная проверка должна быть выполнена в кэше: пропущенная
            # в том запуске = NULL (ФТ-CR-14)
            and (not run_template or existing.template_passed is not None)
            and (
                not run_ai
                or (
                    existing.ai_passed is not None
                    # сменилась модель — кэшированный отчёт ей не соответствовал
                    # (NULL у старых отчётов ≠ модель → разовая ревалидация)
                    and existing.ai_model_used == connection.model
                    # сменился эффективный промт (правка критерия / override) —
                    # кэш не соответствует запрошенной проверке
                    and existing.ai_prompt_hash == prompt_hash
                )
            )
        ):
            return existing  # ничего не изменилось — отчёт актуален

        doc.validation_status = ValidationStatus.IN_PROGRESS
        db.commit()

        template_passed: bool | None = None
        template_findings = ""
        used_template_id: int | None = None
        if run_template:
            # Шаблон требований — выбранная версия или активная (редактируется через UI)
            template = get_template_for_validation(db, template_version_id)
            if template is None:
                return _save_error(db, doc, trigger, "Шаблон требований не настроен")
            template_dict, used_template_id = template
            try:
                template_result = validate_template(doc.title, doc.content_html, template_dict)
            except Exception as exc:  # noqa: BLE001 — любая ошибка = статус error
                return _save_error(db, doc, trigger, f"Ошибка проверки шаблона: {exc}")
            template_passed = template_result.passed
            template_findings = template_result.findings_markdown

        ai_passed: bool | None = None
        ai_findings: str | None = None
        ai_model_used: str | None = None
        if run_ai:
            try:
                markdown = html_to_markdown(doc.content_html)
                # ИИ всегда получает эффективный промт: override или собранный
                # из критериев (None недопустим — валидатор ушёл бы в легаси-промт)
                ai_result = AIValidator(connection=connection).validate(
                    doc.title, markdown, effective_prompt, [c.name for c in criteria]
                )
            except AIValidationError as exc:
                return _save_error(db, doc, trigger, str(exc))
            ai_passed = ai_result.passed
            ai_findings = ai_result.findings_markdown
            ai_model_used = ai_result.model

        # итог = AND по запущенным проверкам (пустой набор невозможен — см. normalize_checks)
        overall = all(passed for passed in (template_passed, ai_passed) if passed is not None)
        report = ValidationReport(
            document_id=doc.id,
            triggered_by=trigger,
            template_passed=template_passed,
            template_findings=template_findings,
            ai_passed=ai_passed,
            ai_findings=ai_findings,
            overall_passed=overall,
            template_version_id=used_template_id,
            # в отчёте храним только override (собранный восстанавливается из критериев)
            ai_prompt=custom_prompt,
            # какой моделью проверяли — для отчёта и идемпотентности (ФТ-CR-14)
            ai_model_used=ai_model_used,
            # чем собирали промт и его хэш — для UI и идемпотентности
            ai_criteria_codes=json.dumps(
                [c.code for c in criteria], ensure_ascii=False
            ),
            ai_prompt_hash=prompt_hash,
        )
        db.add(report)
        doc.validation_status = ValidationStatus.PASSED if overall else ValidationStatus.FAILED
        doc.last_validated_at = now_utc()
        db.commit()
        db.refresh(report)
        return report
