"""Фоновые задачи синхронизации и их состояние (для UI-поллинга)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.services.sync import SyncResult, sync_all, sync_analyst
from app.utils import now_utc

logger = logging.getLogger("confluence_reviewer.tasks")

_sync_state: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "error": None,
    "last_results": [],
}


def sync_status() -> dict[str, Any]:
    return dict(_sync_state)


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
