"""Оценки руководителя по ИИ-критериям: блок оценивания строится по всем
активным критериям справочника (прогоны на него не влияют), upsert 1..10
и «—», stale после перепроверки, архивные критерии скрыты.
"""

from __future__ import annotations

import time

from app.database import Base, SessionLocal, engine
from app.models import Analyst, ConfluenceDocument, CriterionRating, ValidationStatus
from app.services.ai_settings import AIConnection
from app.services.ai_validator import AIValidationResult
from app.services.validation import run_validation
from app.utils import now_utc

import pytest


@pytest.fixture(autouse=True)
def _db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def seed_document(title: str = "[СТ] Доработка") -> int:
    with SessionLocal() as db:
        analyst = Analyst(
            full_name="Тест", email=f"rate-{now_utc().timestamp()}-{id(object())}@mts.ru"
        )
        db.add(analyst)
        db.flush()
        doc = ConfluenceDocument(
            analyst_id=analyst.id,
            confluence_page_id=str(now_utc().timestamp()).replace(".", ""),
            title=title,
            url="https://conf.test/pages/rate",
            content_html="<h1>Введение</h1><h2>Общая информация</h2>",
            last_modified_in_confluence_at=now_utc(),
        )
        db.add(doc)
        db.commit()
        return doc.id


class FakeAIValidator:
    calls = 0

    def __init__(self, *args, **kwargs):
        pass

    def validate(self, title, markdown, system_prompt=None, expected_criteria=None):
        type(self).calls += 1
        return AIValidationResult(
            passed=True, summary="ok", findings_markdown="✅", findings_count=0, model="t"
        )


@pytest.fixture()
def fake_ai(monkeypatch):
    FakeAIValidator.calls = 0
    monkeypatch.setattr("app.services.validation.AIValidator", FakeAIValidator)
    monkeypatch.setattr(
        "app.services.validation.get_ai_connection",
        lambda db: AIConnection(
            protocol="anthropic",
            base_url="https://ai.test",
            api_key="test-key",
            model="t",
            max_tokens=100,
            timeout_seconds=1.0,
        ),
    )
    return FakeAIValidator


def criteria_ids(client) -> list[int]:
    return [c["id"] for c in client.get("/api/ai-criteria").json() if not c["is_archived"]]


def put_rating(client, doc_id: int, criterion_id: int, score: int | None):
    return client.put(
        f"/api/documents/{doc_id}/ratings",
        json={"ratings": [{"criterion_id": criterion_id, "score": score}]},
    )


# --- блок оценивания по активному справочнику ---


def test_ratings_view_ignores_runs(client, fake_ai):
    """Блок виден до первого ИИ-прогона: руководитель оценивает по всем
    активным критериям справочника, а не по набору последнего прогона."""
    doc_id = seed_document()
    ids = criteria_ids(client)

    # прогона не было — блок уже со всеми активными критериями
    body = client.get(f"/api/documents/{doc_id}/ratings").json()
    assert [c["criterion_id"] for c in body["criteria"]] == ids
    assert all(c["score"] is None and not c["stale"] for c in body["criteria"])

    # шаблонная проверка без ИИ блок не меняет
    run_validation(doc_id, checks=["template"])
    body = client.get(f"/api/documents/{doc_id}/ratings").json()
    assert [c["criterion_id"] for c in body["criteria"]] == ids

    # оценка ставится до первого ИИ-прогона
    assert put_rating(client, doc_id, ids[0], 8).status_code == 200


def test_ratings_view_follows_catalog_order(client, fake_ai):
    """Узкий прогон не сужает блок: все активные критерии, порядок справочника."""
    doc_id = seed_document()
    ids = criteria_ids(client)
    run_validation(doc_id, criterion_ids=[ids[2], ids[0]])

    body = client.get(f"/api/documents/{doc_id}/ratings").json()
    # порядок прогона [ids[2], ids[0]] проигнорирован — порядок справочника
    assert [c["criterion_id"] for c in body["criteria"]] == ids
    assert all(c["score"] is None and not c["stale"] for c in body["criteria"])
    assert {c["code"] for c in body["criteria"]} == {
        "polnota_opisaniya",
        "neprotivorechivost_trebovanii",
        "odnoznachnost_formulirovok",
    }


# --- upsert оценок ---


def test_put_upserts_and_removes_rating(client, fake_ai):
    doc_id = seed_document()
    ids = criteria_ids(client)
    run_validation(doc_id)

    body = put_rating(client, doc_id, ids[0], 4).json()
    item = next(c for c in body["criteria"] if c["criterion_id"] == ids[0])
    assert item["score"] == 4 and item["updated_at"] is not None

    # изменение оценки
    body = put_rating(client, doc_id, ids[0], 2).json()
    assert next(c for c in body["criteria"] if c["criterion_id"] == ids[0])["score"] == 2

    # GET видит ту же картину
    body = client.get(f"/api/documents/{doc_id}/ratings").json()
    assert next(c for c in body["criteria"] if c["criterion_id"] == ids[0])["score"] == 2

    # снятие оценки («—») — запись удаляется
    body = put_rating(client, doc_id, ids[0], None).json()
    assert next(c for c in body["criteria"] if c["criterion_id"] == ids[0])["score"] is None
    with SessionLocal() as db:
        assert db.query(CriterionRating).count() == 0
    # повторное снятие идемпотентно
    assert put_rating(client, doc_id, ids[0], None).status_code == 200


def test_rating_survives_new_run_marked_stale(client, fake_ai):
    """Оценка переживает новые прогоны и остаётся видимой: критерий вне
    узкого прогона из блока не исчезает — блок от прогонов не зависит."""
    doc_id = seed_document()
    ids = criteria_ids(client)
    run_validation(doc_id)
    assert put_rating(client, doc_id, ids[1], 5).status_code == 200
    time.sleep(0.01)

    # узкий прогон без второго критерия — блок не сузился, оценка на месте
    run_validation(doc_id, force=True, criterion_ids=[ids[0]])
    body = client.get(f"/api/documents/{doc_id}/ratings").json()
    assert [c["criterion_id"] for c in body["criteria"]] == ids
    item = next(c for c in body["criteria"] if c["criterion_id"] == ids[1])
    assert item["score"] == 5 and item["stale"] is True  # отчёт новее оценки

    # полный прогон — картина та же: оценка жива и помечена устаревшей
    run_validation(doc_id, force=True)
    body = client.get(f"/api/documents/{doc_id}/ratings").json()
    item = next(c for c in body["criteria"] if c["criterion_id"] == ids[1])
    assert item["score"] == 5 and item["stale"] is True


def test_stale_clears_after_rerating(client, fake_ai):
    doc_id = seed_document()
    ids = criteria_ids(client)
    run_validation(doc_id)
    put_rating(client, doc_id, ids[0], 3)
    time.sleep(0.01)
    run_validation(doc_id, force=True)

    body = client.get(f"/api/documents/{doc_id}/ratings").json()
    assert next(c for c in body["criteria"] if c["criterion_id"] == ids[0])["stale"] is True

    body = put_rating(client, doc_id, ids[0], 4).json()
    item = next(c for c in body["criteria"] if c["criterion_id"] == ids[0])
    assert item["stale"] is False and item["score"] == 4


def test_archived_criterion_hidden_even_with_score(client, fake_ai):
    """Архивный критерий исчезает из блока даже с оценкой: оценка живёт
    в БД и статистике, но поставить/снять её на документе уже нельзя."""
    doc_id = seed_document()
    ids = criteria_ids(client)
    run_validation(doc_id)
    assert put_rating(client, doc_id, ids[1], 5).status_code == 200

    client.delete(f"/api/ai-criteria/{ids[1]}")
    body = client.get(f"/api/documents/{doc_id}/ratings").json()
    assert ids[1] not in [c["criterion_id"] for c in body["criteria"]]

    # и поставить, и снять оценку на архивном — 404 с честной причиной
    resp = put_rating(client, doc_id, ids[1], 6)
    assert resp.status_code == 404 and "архиве" in resp.json()["detail"]
    resp = put_rating(client, doc_id, ids[1], None)
    assert resp.status_code == 404 and "архиве" in resp.json()["detail"]

    # запись не стёрта: статистика продолжает считать эту оценку
    with SessionLocal() as db:
        rating = db.query(CriterionRating).filter_by(document_id=doc_id).one()
        assert rating.criterion_id == ids[1] and rating.score == 5


# --- валидация API ---


def test_put_unknown_document_or_criterion_404(client, fake_ai):
    doc_id = seed_document()
    ids = criteria_ids(client)
    assert put_rating(client, 999, ids[0], 3).status_code == 404
    assert put_rating(client, doc_id, 9999, 3).status_code == 404


def test_put_validates_payload(client, fake_ai):
    doc_id = seed_document()
    ids = criteria_ids(client)
    run_validation(doc_id)

    # новые границы шкалы: 6 и 10 валидны, 11 и 0 — нет
    assert put_rating(client, doc_id, ids[0], 6).status_code == 200
    assert put_rating(client, doc_id, ids[0], 10).status_code == 200
    assert put_rating(client, doc_id, ids[0], 11).status_code == 422
    assert put_rating(client, doc_id, ids[0], 0).status_code == 422
    # пустой список и дубликаты критериев
    assert (
        client.put(f"/api/documents/{doc_id}/ratings", json={"ratings": []}).status_code == 422
    )
    dup = client.put(
        f"/api/documents/{doc_id}/ratings",
        json={"ratings": [
            {"criterion_id": ids[0], "score": 1},
            {"criterion_id": ids[0], "score": 2},
        ]},
    )
    assert dup.status_code == 422
