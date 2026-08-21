"""Общие утилиты времени: всё хранится в наивном UTC (единообразно sqlite/postgres)."""

from __future__ import annotations

from datetime import datetime, timezone


def now_utc() -> datetime:
    """Текущий момент в наивном UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
