"""Статистика оценок руководителя в профиле аналитика: средние по критериям,
число оценок, общий балл и фильтр по периоду (дата создания документа)."""

from __future__ import annotations

from datetime import datetime

from app.database import Base, SessionLocal, engine
from app.models import AiCriterion, Analyst, ConfluenceDocument, CriterionRating
from app.utils import now_utc

import pytest


@pytest.fixture(autouse=True)
def _db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _seed(
    name: str,
    rated: list[list[tuple[int, int]]],
    created: list[datetime | None] | None = None,
) -> tuple[int, list[int]]:
    """Аналитик с документами и оценками: rated[i] — оценки i-го документа,
    каждая — (индекс критерия 0/1, балл). Возвращает (analyst_id, criterion_ids).

    created — даты создания документов (по одной на документ, None — без даты):
    статистика фильтрует по ним, поэтому тестам периода нужны фикс. границы.
    Без параметра даты создания не задаются.

    Критерий 0 — активный, 1 — архивный: статистика показывает оба. Коды
    критериев уникальны на вызов — нескольких аналитиков в тесте можно сеять.
    """
    suffix = f"{now_utc().timestamp()}-{id(object())}"
    with SessionLocal() as db:
        analyst = Analyst(full_name=name, email=f"stats-{suffix}@mts.ru")
        db.add(analyst)
        db.flush()

        crit_ids = [
            _add_criterion(db, f"stat_code_a_{suffix}", "А-критерий", is_archived=False),
            _add_criterion(db, f"stat_code_b_{suffix}", "Б-критерий", is_archived=True),
        ]

        for i, scores in enumerate(rated):
            doc = ConfluenceDocument(
                analyst_id=analyst.id,
                confluence_page_id=f"stat-{now_utc().timestamp()}-{analyst.id}-{i}",
                title=f"[СТ] Документ {i}",
                url="https://conf.test/pages/stat",
                content_html="<h1>Введение</h1>",
                created_in_confluence_at=created[i] if created is not None else None,
            )
            db.add(doc)
            db.flush()
            for criterion_idx, score in scores:
                db.add(
                    CriterionRating(
                        document_id=doc.id, criterion_id=crit_ids[criterion_idx], score=score
                    )
                )
        db.commit()
        return analyst.id, crit_ids


def _add_criterion(db, code: str, name: str, *, is_archived: bool) -> int:
    criterion = AiCriterion(code=code, name=name, prompt="проверить", is_archived=is_archived)
    db.add(criterion)
    db.flush()
    return criterion.id


def test_summary_empty_without_ratings(client):
    analyst_id, _ = _seed("Без оценок", [[], []])

    body = client.get(f"/api/analysts/{analyst_id}/ratings-summary").json()
    assert body == {
        "analyst_id": analyst_id,
        "date_from": None,
        "date_to": None,
        "overall_average": None,
        "total_ratings": 0,
        "criteria": [],
    }


def test_summary_averages_and_order(client):
    # критерий 0: (4 + 2) / 2 = 3.0; архивный критерий 1: 5.0 — он и первый
    analyst_id, crit_ids = _seed("Статистик", [[(0, 4), (1, 5)], [(0, 2)]])

    # чужие оценки в статистику аналитика не попадают
    _seed("Чужой", [[(0, 1)]])

    body = client.get(f"/api/analysts/{analyst_id}/ratings-summary").json()
    assert body["total_ratings"] == 3
    assert body["overall_average"] == 3.67  # (4 + 5 + 2) / 3
    # от сильных к слабым: архивный «Б» (5.0) выше активного «А» (3.0)
    assert [c["criterion_id"] for c in body["criteria"]] == [crit_ids[1], crit_ids[0]]
    by_id = {c["criterion_id"]: c for c in body["criteria"]}
    assert by_id[crit_ids[0]]["average"] == 3.0
    assert by_id[crit_ids[0]]["ratings_count"] == 2
    assert by_id[crit_ids[0]]["is_archived"] is False
    assert by_id[crit_ids[1]]["average"] == 5.0
    assert by_id[crit_ids[1]]["ratings_count"] == 1
    assert by_id[crit_ids[1]]["is_archived"] is True


def test_summary_period_filters_by_document_creation(client):
    # документ создан 10 августа: август видит его оценку, июль и сентябрь — нет
    analyst_id, _ = _seed("Период", [[(0, 3)]], created=[datetime(2026, 8, 10)])
    base = f"/api/analysts/{analyst_id}/ratings-summary"

    assert (
        client.get(f"{base}?date_from=2026-08-01&date_to=2026-08-31").json()["total_ratings"] == 1
    )
    assert client.get(f"{base}?date_to=2026-07-31").json()["total_ratings"] == 0
    assert client.get(f"{base}?date_from=2026-09-01").json()["total_ratings"] == 0
    # границы периода возвращаются в ответе; «по» — эффективная граница
    body = client.get(f"{base}?date_from=2026-08-01&date_to=2026-08-31").json()
    assert body["date_from"] == "2026-08-01T00:00:00"
    assert body["date_to"] == "2026-08-31T23:59:59.999999"


def test_summary_period_ignores_rating_updated_at(client):
    # семантика — по созданию документа: когда именно выставлен балл, не важно
    analyst_id, _ = _seed("Игнор даты оценки", [[(0, 4)]], created=[datetime(2026, 8, 10)])
    base = f"/api/analysts/{analyst_id}/ratings-summary"
    with SessionLocal() as db:
        rating = db.query(CriterionRating).one()
        rating.updated_at = datetime(2000, 1, 1)
        db.commit()
    assert (
        client.get(f"{base}?date_from=2026-08-01&date_to=2026-08-31").json()["total_ratings"] == 1
    )
    with SessionLocal() as db:
        rating = db.query(CriterionRating).one()
        rating.updated_at = datetime(2100, 1, 1)
        db.commit()
    assert (
        client.get(f"{base}?date_from=2026-08-01&date_to=2026-08-31").json()["total_ratings"] == 1
    )


def test_summary_period_boundaries_inclusive(client):
    # документы ровно на границах периода входят в статистику
    analyst_id, _ = _seed(
        "Границы",
        [[(0, 4)], [(0, 5)]],
        created=[datetime(2026, 8, 1), datetime(2026, 8, 31, 23, 59, 59, 999999)],
    )
    base = f"/api/analysts/{analyst_id}/ratings-summary"
    body = client.get(f"{base}?date_from=2026-08-01&date_to=2026-08-31").json()
    assert body["total_ratings"] == 2


def test_summary_period_excludes_null_created_at(client):
    # оценка на документе без даты создания: вне периода, в «за всё время» — есть
    analyst_id, _ = _seed("Без даты", [[(0, 3)]], created=[None])
    base = f"/api/analysts/{analyst_id}/ratings-summary"
    assert (
        client.get(f"{base}?date_from=2000-01-01&date_to=2100-01-01").json()["total_ratings"] == 0
    )
    assert client.get(base).json()["total_ratings"] == 1


def test_summary_period_naive_aware_mixture_ok(client):
    # date_from date-only (naive) + date_to со «Z» (aware): не 500, а честный ответ
    analyst_id, _ = _seed("Смешение", [[(0, 4)]], created=[datetime(2026, 8, 10)])
    resp = client.get(
        f"/api/analysts/{analyst_id}/ratings-summary"
        "?date_from=2026-08-01&date_to=2026-08-31T00:00:00Z"
    )
    assert resp.status_code == 200
    assert resp.json()["total_ratings"] == 1


def test_summary_period_from_after_to_422(client):
    analyst_id, _ = _seed("Перевёрнутый", [[(0, 3)]], created=[datetime(2026, 8, 10)])
    assert (
        client.get(
            f"/api/analysts/{analyst_id}/ratings-summary?date_from=2026-08-31&date_to=2026-08-01"
        ).status_code
        == 422
    )


def test_summary_unknown_analyst_404(client):
    assert client.get("/api/analysts/999/ratings-summary").status_code == 404


def test_summary_validates_dates(client):
    assert (
        client.get("/api/analysts/1/ratings-summary?date_from=not-a-date").status_code == 422
    )
