"""Оценки руководителя по ИИ-критериям: блок оценивания строится по
последнему прогону документа, upsert 1..5 и «—», stale после перепроверки.
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

    def validate(self, title, markdown, system_prompt=None):
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


# --- блок оценивания по последнему прогону ---


def test_ratings_view_requires_ai_run(client, fake_ai):
    doc_id = seed_document()
    # прогона не было — оценивать нечего
    assert client.get(f"/api/documents/{doc_id}/ratings").json()["criteria"] == []

    # шаблонная проверка без ИИ тоже не даёт критериев для оценки
    run_validation(doc_id, checks=["template"])
    assert client.get(f"/api/documents/{doc_id}/ratings").json()["criteria"] == []


def test_ratings_view_follows_last_run_order(client, fake_ai):
    doc_id = seed_document()
    ids = criteria_ids(client)
    run_validation(doc_id, criterion_ids=[ids[2], ids[0]])

    body = client.get(f"/api/documents/{doc_id}/ratings").json()
    assert [c["criterion_id"] for c in body["criteria"]] == [ids[2], ids[0]]
    assert all(c["score"] is None and not c["stale"] for c in body["criteria"])
    # название и архивность — из справочника, для блока оценивания
    assert {c["code"] for c in body["criteria"]} == {
        "odnoznachnost_formulirovok",
        "polnota_opisaniya",
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


def test_rating_survives_new_run_hidden_until_criteria_return(client, fake_ai):
    """Оценка вне текущего прогона не показывается, но хранится: критерий
    вернётся в прогон — оценка вернётся в блок (как устаревшая)."""
    doc_id = seed_document()
    ids = criteria_ids(client)
    run_validation(doc_id)
    assert put_rating(client, doc_id, ids[1], 5).status_code == 200
    time.sleep(0.01)

    # узкий прогон без второго критерия
    run_validation(doc_id, force=True, criterion_ids=[ids[0]])
    body = client.get(f"/api/documents/{doc_id}/ratings").json()
    assert [c["criterion_id"] for c in body["criteria"]] == [ids[0]]

    # полный прогон снова — оценка на месте, но отчёт новее неё
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


def test_archived_criterion_of_run_is_ratable(client, fake_ai):
    """Критерий прогонa заархивировали — блок оценивания его не теряет."""
    doc_id = seed_document()
    ids = criteria_ids(client)
    run_validation(doc_id)
    client.delete(f"/api/ai-criteria/{ids[1]}")

    body = client.get(f"/api/documents/{doc_id}/ratings").json()
    item = next(c for c in body["criteria"] if c["criterion_id"] == ids[1])
    assert item["is_archived"] is True

    assert put_rating(client, doc_id, ids[1], 5).status_code == 200
    body = client.get(f"/api/documents/{doc_id}/ratings").json()
    assert next(c for c in body["criteria"] if c["criterion_id"] == ids[1])["score"] == 5


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

    # оценка вне диапазона 1..5
    assert put_rating(client, doc_id, ids[0], 6).status_code == 422
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
