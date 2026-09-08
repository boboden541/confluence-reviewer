"""Фоновые задачи синхронизации и валидации, их состояние для UI.

Состояние доступно двумя путями: REST-эндпоинты статуса (разовый опрос) и
события SSE /api/events — их получает каждый подписчик в момент изменения
(см. _publish_event): итог задачи сам появляется на открытой странице.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

from app import repository
from app.database import SessionLocal
from app.models import TriggerType
from app.usecase.sync import SyncResult, sync_all, sync_analyst
from app.usecase.validation import DocumentNotFound, run_validation
from app.utils import now_utc

logger = logging.getLogger("confluence_reviewer.tasks")

_UNSET = object()  # «не передано»: валидация сама считает эффективное подключение

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


# --- события для UI (SSE /api/events) ---

# Очередь событий на каждого подписчика стрима. Живёт в event loop сервера
# (uvicorn в один воркер), поэтому put_nowait из корутин безопасен.
_event_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

# Журнал последних событий для ленты на главной: события живут и после
# рассылки (пришёл позже — видишь, что пропустил), ограничены по глубине.
_event_journal: deque[dict[str, Any]] = deque(maxlen=50)


def subscribe_events() -> asyncio.Queue[dict[str, Any]]:
    """Очередь событий для нового SSE-подписчика (+снимок текущих состояний).

    Снимок нужен странице, открытой посреди прогона: без него прогресс
    уже идущей задачи она бы не увидела до следующего события.
    """
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    _event_subscribers.add(queue)
    queue.put_nowait({"type": "sync", **sync_status()})
    queue.put_nowait({"type": "bulk", **bulk_status()})
    return queue


def unsubscribe_events(queue: asyncio.Queue[dict[str, Any]]) -> None:
    _event_subscribers.discard(queue)


def recent_events(limit: int = 30) -> list[dict[str, Any]]:
    """Последние события (свежие сверху) — для ленты на главной."""
    events = list(_event_journal)
    events.reverse()
    return events[:limit]


def _publish_event(event_type: str, payload: dict[str, Any]) -> None:
    """Записать событие в журнал и разослать подписчикам.

    Звать только из корутин event loop. Журнал пополняется всегда — даже
    когда подписчиков нет: лента главной показывает события, случившиеся
    до открытия страницы. Журналу и каждому подписчику уходит своя копия:
    потребитель, поменявший полученное событие, не переписывает историю.
    """
    event = {"type": event_type, "at": now_utc().isoformat(), **payload}
    _event_journal.append(dict(event))
    if not _event_subscribers:
        return
    for queue in list(_event_subscribers):
        queue.put_nowait(dict(event))


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
        _publish_event("sync", sync_status())
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
            _publish_event("sync", sync_status())

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False, "Нет активного event loop"

    asyncio.create_task(runner())
    return True, "Синхронизация запущена"


def _run_validation_sync(document_id: int, **kwargs) -> Any:
    """Сессия БД для фоновой валидации (run_validation работает по сессии)."""
    with SessionLocal() as db:
        return run_validation(db, document_id, **kwargs)


def _actor_fields(actor_user) -> dict:
    """Атрибуты события для «Моей активности» (кто запустил прогон)."""
    if actor_user is None:
        return {}
    return {"actor_id": actor_user.id, "actor_name": actor_user.full_name}


async def _execute_validation(
    document_id: int,
    trigger: TriggerType,
    force: bool,
    template_version_id: int | None = None,
    ai_prompt: str | None = None,
    checks: list[str] | None = None,
    criterion_ids: list[int] | None = None,
    ai_connection: Any = _UNSET,
    owner_user=None,
) -> Any:
    """Реальная работа; отдельная функция — точка подмены в тестах."""
    extra: dict[str, Any] = {}
    if ai_connection is not _UNSET:
        extra["ai_connection"] = ai_connection
    if owner_user is not None:
        extra["owner_user"] = owner_user
    return await asyncio.to_thread(
        _run_validation_sync,
        document_id,
        trigger=trigger,
        force=force,
        template_version_id=template_version_id,
        ai_prompt=ai_prompt,
        checks=checks,
        criterion_ids=criterion_ids,
        **extra,
    )


def start_validation(
    document_id: int,
    *,
    trigger: TriggerType = TriggerType.MANUAL,
    force: bool = False,
    template_version_id: int | None = None,
    ai_prompt: str | None = None,
    checks: list[str] | None = None,
    criterion_ids: list[int] | None = None,
    ai_connection: Any = _UNSET,
    owner_user=None,
    actor_user=None,
) -> tuple[bool, str]:
    """Запустить валидацию документа в фоне (ФТ-CR-16). True — запущена.

    template_version_id / ai_prompt / checks / criterion_ids — настройки
    из диалога проверки.
    """
    current = _validation_state.get(document_id)
    if current and current.get("status") == "running":
        return False, "Валидация документа уже выполняется"

    async def runner() -> None:
        _validation_state[document_id] = {
            "status": "running",
            "started_at": now_utc().isoformat(),
            "error": None,
        }
        _publish_event(
            "validation",
            {"document_id": document_id, **_validation_state[document_id], **_actor_fields(actor_user)},
        )
        extra: dict[str, Any] = {}
        if ai_connection is not _UNSET:
            extra["ai_connection"] = ai_connection
        if owner_user is not None:
            extra["owner_user"] = owner_user
        try:
            report = await _execute_validation(
                document_id,
                trigger,
                force,
                template_version_id,
                ai_prompt,
                checks,
                criterion_ids,
                **extra,
            )
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
        _publish_event(
            "validation",
            {"document_id": document_id, **_validation_state[document_id], **_actor_fields(actor_user)},
        )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False, "Нет активного event loop"

    loop.create_task(runner())
    return True, "Валидация запущена"


def bulk_status() -> dict[str, Any]:
    return dict(_bulk_state)


def start_bulk_validation(
    document_ids: list[int],
    analyst_id: int | None = None,
    *,
    force: bool = False,
    template_version_id: int | None = None,
    ai_prompt: str | None = None,
    checks: list[str] | None = None,
    criterion_ids: list[int] | None = None,
    ai_connection: Any = _UNSET,
    owner_user=None,
    actor_user=None,
) -> tuple[bool, str]:
    """Проверить документы последовательно, в фоне (выбор пользователя
    в списке или «все документы аналитика»).

    Не-force: актуальные (не менявшиеся после последней проверки) документы
    пропускаются идемпотентностью run_validation. Последовательный прогон —
    чтобы не упереться в лимиты ИИ-провайдера.
    """
    if _bulk_state["running"]:
        return False, "Массовая проверка уже выполняется"
    if not document_ids:
        return False, "Не выбраны документы для проверки"

    async def runner() -> None:
        _bulk_state.update(
            running=True,
            analyst_id=analyst_id,
            total=len(document_ids),
            done=0,
            started_at=now_utc().isoformat(),
            finished_at=None,
            error=None,
        )
        _publish_event("bulk", {**bulk_status(), **_actor_fields(actor_user)})
        try:
            for doc_id in document_ids:
                _validation_state[doc_id] = {
                    "status": "running",
                    "started_at": now_utc().isoformat(),
                    "error": None,
                }
                _publish_event(
                    "validation",
                    {"document_id": doc_id, **_validation_state[doc_id], **_actor_fields(actor_user)},
                )
                extra: dict[str, Any] = {}
                if ai_connection is not _UNSET:
                    extra["ai_connection"] = ai_connection
                if owner_user is not None:
                    extra["owner_user"] = owner_user
                try:
                    report = await _execute_validation(
                        doc_id,
                        TriggerType.MANUAL,
                        force,
                        template_version_id,
                        ai_prompt,
                        checks,
                        criterion_ids,
                        **extra,
                    )
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
                _publish_event(
                    "validation",
                    {"document_id": doc_id, **_validation_state[doc_id], **_actor_fields(actor_user)},
                )
                _bulk_state["done"] += 1
                _publish_event("bulk", {**bulk_status(), **_actor_fields(actor_user)})
        finally:
            _bulk_state.update(running=False, finished_at=now_utc().isoformat())
            _publish_event("bulk", bulk_status())

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False, "Нет активного event loop"

    loop.create_task(runner())
    return True, "Массовая проверка запущена"


def start_analyst_bulk_validation(
    analyst_id: int, *, actor_user=None, ai_connection: Any = _UNSET, owner_user=None
) -> tuple[bool, str]:
    """«Проверить все документы аналитика»: набор id из БД (legacy-эндпоинт)."""
    with SessionLocal() as db:
        doc_ids = repository.documents.ids_for_analyst(db, analyst_id)
    if not doc_ids:
        return False, "У аналитика нет документов для проверки"
    return start_bulk_validation(
        doc_ids,
        analyst_id,
        actor_user=actor_user,
        ai_connection=ai_connection,
        owner_user=owner_user,
    )
