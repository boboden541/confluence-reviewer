"""Схемы оценок руководителя и статистики по аналитику."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class RatingItem(BaseModel):
    """Одна оценка в PUT: score=None — снять оценку («—»)."""

    criterion_id: int
    score: int | None = Field(default=None, ge=1, le=10)


class RatingsUpdate(BaseModel):
    """PUT /api/documents/{id}/ratings: применить оценки (upsert по паре
    документ+критерий). Достаточно изменившихся элементов, не всего блока."""

    ratings: list[RatingItem] = Field(min_length=1, max_length=100)

    @field_validator("ratings")
    @classmethod
    def no_duplicate_criteria(cls, value: list[RatingItem]) -> list[RatingItem]:
        seen = {item.criterion_id for item in value}
        if len(seen) != len(value):
            raise ValueError("Каждый критерий — не более одной оценки в запросе")
        return value


class RatingItemOut(BaseModel):
    """Активный критерий справочника с оценкой руководителя (если есть)."""

    criterion_id: int
    code: str
    name: str
    # задел: блок строится только по активным — из API всегда False
    is_archived: bool
    # None — оценка ещё не выставлена («—»)
    score: int | None = None
    updated_at: datetime | None = None
    # Документ перепроверен после оценки — оценка могла устареть
    stale: bool = False


class RatingsOut(BaseModel):
    """Блок оценивания документа: все активные критерии справочника по порядку.

    Пустой criteria — в справочнике нет активных критериев (архив не в счёт):
    оценивать нечего.
    """

    document_id: int
    criteria: list[RatingItemOut] = Field(default_factory=list)


# --- Статистика оценок аналитика (профиль) ---


class CriterionSummaryOut(BaseModel):
    """Средний балл и число оценок по одному критерию."""

    criterion_id: int
    code: str
    name: str
    is_archived: bool
    average: float
    ratings_count: int


class RatingsSummaryOut(BaseModel):
    """Средние оценки руководителя по критериям аналитика за период.

    Период — по дате создания документа в Confluence (created_in_confluence_at),
    границы включительны. date_to возвращается эффективной границей: date-only
    «по» расширяется до конца суток.
    """

    analyst_id: int
    date_from: datetime | None = None
    date_to: datetime | None = None
    # None — оценок в периоде нет
    overall_average: float | None = None
    total_ratings: int = 0
    criteria: list[CriterionSummaryOut] = Field(default_factory=list)
