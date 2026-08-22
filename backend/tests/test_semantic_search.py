"""Тесты семантического поиска документов через GLM."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.database import SessionLocal
from app.models import Analyst, ConfluenceDocument, DocumentNote
from app.routers import documents as documents_router
from app.services import semantic_search as ss
from app.services.semantic_search import SemanticSearchError


def seed_analyst_with_docs(titles: list[str]) -> tuple[int, list[int]]:
    with SessionLocal() as db:
        analyst = Analyst(full_name="Поиск", email="semantic@mts.ru")
        db.add(analyst)
        db.flush()
        ids: list[int] = []
        for i, title in enumerate(titles):
            doc = ConfluenceDocument(
                analyst_id=analyst.id,
                confluence_page_id=f"sem{i:04d}",
                title=title,
                url=f"https://conf.test/pages/sem{i}",
                content_html="<h1>Введение</h1>",
            )
            db.add(doc)
            db.flush()
            ids.append(doc.id)
        db.commit()
        return analyst.id, ids


class StubSearcher:
    """Подмена ИИ-поиска: заранее заданный результат или ошибка."""

    def __init__(self, matches=None, error: Exception | None = None):
        self.matches = matches or []
        self.error = error
        self.calls: list[tuple[int, str, list]] = []

    def search(self, analyst_id: int, query: str, docs: list):
        self.calls.append((analyst_id, query, list(docs)))
        if self.error is not None:
            raise self.error
        return self.matches


# --- разбор ответа модели ---


def test_parse_matches_filters_clamps_and_sorts():
    text = """```json
    {"matches": [
        {"id": 2, "score": 0.9},
        {"id": 7, "score": 1.5},
        {"id": 2, "score": 0.5},
        {"id": 99, "score": 0.8},
        {"id": "мусор", "score": 1}
    ]}
    ```"""
    matches = ss.parse_matches(text, known_ids={2, 7})
    # неизвестный id выброшен, дубль схлопнут по максимуму, score зажат в 0..1
    assert matches == [(7, 1.0), (2, 0.9)]


def test_parse_matches_empty_when_nothing_matches():
    assert ss.parse_matches('{"matches": []}', known_ids={1}) == []


def test_build_user_prompt_lists_documents():
    prompt = ss.build_user_prompt("загрузка кино", [(11, "[СТ] GDS-15 Кино"), (12, "[СТ] Биллинг")])
    assert "загрузка кино" in prompt
    assert "11. [СТ] GDS-15 Кино" in prompt
    assert "12. [СТ] Биллинг" in prompt


# --- сервис: вызов ИИ + кэш ---


class FakeClient:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    @property
    def messages(self):
        inner = self

        class _Messages:
            def create(self, **kwargs):
                inner.calls += 1
                return SimpleNamespace(
                    content=[SimpleNamespace(type="text", text=inner.text)]
                )

        return _Messages()


def test_search_parses_response_and_caches():
    text = '{"matches": [{"id": 2, "score": 0.9}, {"id": 7, "score": 0.4}]}'
    client = FakeClient(text)
    searcher = ss.SemanticSearcher(client=client)
    docs = [(2, "Заголовок 2"), (7, "Заголовок 7")]
    assert searcher.search(1, "запрос", docs) == [(2, 0.9), (7, 0.4)]

    # тот же запрос (регистр/пробелы не важны) — из кэша, без нового вызова ИИ
    assert searcher.search(1, "  ЗАПРОС ", docs) == [(2, 0.9), (7, 0.4)]
    assert client.calls == 1


def test_search_unparseable_response_raises():
    searcher = ss.SemanticSearcher(client=FakeClient("ИИ сломался и вернул текст"))
    with pytest.raises(SemanticSearchError):
        searcher.search(1, "запрос", [(2, "Заголовок")])


# --- API ---


def test_semantic_endpoint_orders_by_score(client, monkeypatch):
    analyst_id, doc_ids = seed_analyst_with_docs(["Кино", "Биллинг", "Склад"])
    with SessionLocal() as db:
        db.add(DocumentNote(document_id=doc_ids[0], content="заметка"))
        db.commit()

    stub = StubSearcher(matches=[(doc_ids[0], 0.9), (doc_ids[2], 0.4)])
    monkeypatch.setattr(documents_router, "searcher", stub)

    resp = client.get(f"/api/analysts/{analyst_id}/documents/semantic", params={"query": "фильмы"})
    assert resp.status_code == 200
    body = resp.json()
    assert [item["id"] for item in body["items"]] == [doc_ids[0], doc_ids[2]]
    assert body["items"][0]["score"] == 0.9
    assert body["items"][1]["score"] == 0.4
    assert body["items"][0]["has_note"] is True
    assert body["items"][1]["has_note"] is False
    # в поиск ушли id и заголовки документов именно этого аналитика
    analyst_arg, query_arg, docs_arg = stub.calls[0]
    assert analyst_arg == analyst_id and query_arg == "фильмы"
    assert {doc_id for doc_id, _ in docs_arg} == set(doc_ids)


def test_semantic_endpoint_respects_limit(client, monkeypatch):
    analyst_id, doc_ids = seed_analyst_with_docs(["A", "B", "C"])
    stub = StubSearcher(matches=[(doc_ids[0], 0.9), (doc_ids[1], 0.5), (doc_ids[2], 0.4)])
    monkeypatch.setattr(documents_router, "searcher", stub)

    body = client.get(
        f"/api/analysts/{analyst_id}/documents/semantic",
        params={"query": "тест", "limit": 2},
    ).json()
    assert len(body["items"]) == 2
    assert body["total"] == 2


def test_semantic_endpoint_no_documents(client, monkeypatch):
    with SessionLocal() as db:
        db.add(Analyst(full_name="Пусто", email="empty-sem@mts.ru"))
        db.commit()
    stub = StubSearcher()
    monkeypatch.setattr(documents_router, "searcher", stub)

    body = client.get("/api/analysts/1/documents/semantic", params={"query": "что-то"}).json()
    assert body == {"items": [], "total": 0, "page": 1, "page_size": 20}
    assert stub.calls == []  # ИИ не дёргаем


def test_semantic_endpoint_ai_failure_is_502(client, monkeypatch):
    analyst_id, _ = seed_analyst_with_docs(["A"])
    monkeypatch.setattr(
        documents_router, "searcher", StubSearcher(error=SemanticSearchError("нет связи"))
    )
    resp = client.get(f"/api/analysts/{analyst_id}/documents/semantic", params={"query": "тест"})
    assert resp.status_code == 502
    assert "нет связи" in resp.json()["detail"]


def test_semantic_endpoint_validation_and_not_found(client, monkeypatch):
    monkeypatch.setattr(documents_router, "searcher", StubSearcher())
    # запрос короче 2 символов — 422, ИИ не вызывается
    assert (
        client.get("/api/analysts/1/documents/semantic", params={"query": "я"}).status_code == 422
    )
    assert client.get("/api/analysts/999/documents/semantic", params={"query": "тест"}).status_code == 404
