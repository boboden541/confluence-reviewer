"""Фоновые задачи синхронизации и валидации, их состояние (для UI-поллинга)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select

from app.database import SessionLocal
from app.models import ConfluenceDocument, TriggerType
from app.services.sync import SyncResult, sync_all, sync_analyst
from app.services.validation import DocumentNotFound, run_validation
from app.utils import now_utc

logger = logging.getLogger("confluence_reviewer.tasks")

_sync_state: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "error": None,
    "last_results": [],
}

# document_id -> {"status": running|done|error|not_found, "report_id", "error", ...}
_validation_state: dict[int, dict[str, Any]] = {}

# Массовая проверка документов аналитика (запускается вручную)
_bulk_state: dict[str, Any] = {
    "running": False,
    "analyst_id": None,
    "total": 0,
    "done": 0,
    "started_at": None,
    "finished_at": None,
    "error": None,
}


def sync_status() -> dict[str, Any]:
    return dict(_sync_state)


def validation_status() -> dict[int, dict[str, Any]]:
    return {doc_id: dict(state) for doc_id, state in _validation_state.items()}


async def _execute_sync(analyst_id: int | None) -> list[SyncResult]:
    """Реальная работа; отдельная функция — точка подмены в тестах."""
    if analyst_id is not None:
        return [await sync_analyst(analyst_id)]
    return await sync_all()


def start_sync(analyst_id: int | None = None) -> tuple[bool, str]:
    """Запустить синхронизацию в фоне (ФТ-CR-6). True — запущена."""
    if _sync_state["running"]:
        return False, "Синхронизация уже выполняется"

    async def runner() -> None:
        _sync_state.update(
            running=True, started_at=now_utc().isoformat(), finished_at=None, error=None
        )
        try:
            results = await _execute_sync(analyst_id)
            _sync_state["last_results"] = [
                {
                    "analyst_id": r.analyst_id,
                    "analyst_name": r.analyst_name,
                    "created": r.created,
                    "updated": r.updated,
                    "error": r.error,
                }
                for r in results
            ]
            # Валидации запускаются только вручную: синхронизация лишь обновляет
            # список и содержимое документов (замечание заказчика 2026-08-22).
        except Exception as exc:  # noqa: BLE001 — фоновая задача не должна ронять процесс
            logger.exception("Фоновая синхронизация упала")
            _sync_state["error"] = str(exc)
        finally:
            _sync_state.update(running=False, finished_at=now_utc().isoformat())

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False, "Нет активного event loop"

    asyncio.create_task(runner())
    return True, "Синхронизация запущена"


async def _execute_validation(
    document_id: int, trigger: TriggerType, force: bool
) -> Any:
    """Реальная работа; отдельная функция — точка подмены в тестах."""
    return await asyncio.to_thread(
        run_validation, document_id, trigger=trigger, force=force
    )


def start_validation(
    document_id: int,
    *,
    trigger: TriggerType = TriggerType.MANUAL,
    force: bool = False,
) -> tuple[bool, str]:
    """Запустить валидацию документа в фоне (ФТ-CR-16). True — запущена."""
    current = _validation_state.get(document_id)
    if current and current.get("status") == "running":
        return False, "Валидация документа уже выполняется"

    async def runner() -> None:
        _validation_state[document_id] = {
            "status": "running",
            "started_at": now_utc().isoformat(),
            "error": None,
        }
        try:
            report = await _execute_validation(document_id, trigger, force)
            _validation_state[document_id].update(
                status="done", report_id=report.id, finished_at=now_utc().isoformat()
            )
        except DocumentNotFound:
            _validation_state[document_id].update(
                status="not_found", error="Документ не найден"
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Фоновая валидация документа %s упала", document_id)
            _validation_state[document_id].update(status="error", error=str(exc))

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False, "Нет активного event loop"

    loop.create_task(runner())
    return True, "Валидация запущена"


def bulk_status() -> dict[str, Any]:
    return dict(_bulk_state)


def start_bulk_validation(analyst_id: int) -> tuple[bool, str]:
    """Проверить все документы аналитика последовательно, в фоне.

    Не-force: актуальные (не менявшиеся после последней проверки) документы
    пропускаются идемпотентностью run_validation. Последовательный прогон —
    чтобы не упереться в лимиты ИИ-провайдера.
    """
    if _bulk_state["running"]:
        return False, "Массовая проверка уже выполняется"

    with SessionLocal() as db:
        doc_ids = (
            db.scalars(
                select(ConfluenceDocument.id)
                .where(ConfluenceDocument.analyst_id == analyst_id)
                .order_by(ConfluenceDocument.id)
            )
            .all()
        )

    if not doc_ids:
        return False, "У аналитика нет документов для проверки"

    async def runner() -> None:
        _bulk_state.update(
            running=True,
            analyst_id=analyst_id,
            total=len(doc_ids),
            done=0,
            started_at=now_utc().isoformat(),
            finished_at=None,
            error=None,
        )
        try:
            for doc_id in doc_ids:
                _validation_state[doc_id] = {
                    "status": "running",
                    "started_at": now_utc().isoformat(),
                    "error": None,
                }
                try:
                    report = await _execute_validation(doc_id, TriggerType.MANUAL, False)
                    _validation_state[doc_id].update(
                        status="done", report_id=report.id, finished_at=now_utc().isoformat()
                    )
                except DocumentNotFound:
                    _validation_state[doc_id].update(
                        status="not_found", error="Документ не найден"
                    )
                except Exception as exc:  # noqa: BLE001 — один документ не роняет прогон
                    logger.exception("Массовая валидация: документ %s упал", doc_id)
                    _validation_state[doc_id].update(status="error", error=str(exc))
                _bulk_state["done"] += 1
        finally:
            _bulk_state.update(running=False, finished_at=now_utc().isoformat())

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False, "Нет активного event loop"

    loop.create_task(runner())
    return True, "Массовая проверка запущена"
