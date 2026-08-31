"""Общие утилиты времени: всё хранится в наивном UTC (единообразно sqlite/postgres)."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone


def now_utc() -> datetime:
    """Текущий момент в наивном UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(value: datetime | None) -> datetime | None:
    """Граница периода из запроса — к наивному UTC (см. now_utc).

    pydantic парсит date-only и «...Z»/«+03:00» по-разному: naive и aware.
    Смешение aware с naive роняет сравнение в Python (TypeError → 500),
    а aware в SQL-сравнении с наивной колонкой молча теряет offset —
    поэтому приводим к наивному UTC до любого использования.
    """
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def normalize_period_end(value: datetime) -> datetime:
    """Верхняя граница периода «по дату включительно» (наивный UTC).

    Дата с нулевым временем суток (date-only запросы парсятся ровно в
    полночь) расширяется до конца суток — иначе сравнение <= отбросило бы
    весь последний день периода. Точное время — точная граница, как задано.
    """
    if value.time() == time(0, 0, 0, 0):
        return value + timedelta(days=1) - timedelta(microseconds=1)
    return value
