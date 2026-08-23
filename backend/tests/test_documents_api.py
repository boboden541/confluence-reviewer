"""Тесты API документов: сортировка, пагинация, поиск (ФТ-CR-7..ФТ-CR-9)."""

from __future__ import annotations

from datetime import timedelta

from app.database import SessionLocal
from app.models import Analyst, ConfluenceDocument, ValidationStatus
from app.utils import now_utc


def seed_analyst_with_docs(count: int = 5, title_pattern: str = "Страница {n}") -> tuple[int, list[int]]:
    """Аналитик + count документов с разными датами создания."""
    with SessionLocal() as db:
        analyst = Analyst(full_name="Тест", email="t@mts.ru")
        db.add(analyst)
        db.flush()
        ids = []
        for n in range(1, count + 1):
            doc = ConfluenceDocument(
                analyst_id=analyst.id,
                confluence_page_id=str(1000 + n),
                title=title_pattern.format(n=n),
                url=f"https://conf.test/pages/viewpage.action?pageId={1000 + n}",
                content_html="<h1>Введение</h1>",
                created_in_confluence_at=now_utc() - timedelta(days=count - n + 1),
                last_modified_in_confluence_at=now_utc() - timedelta(days=1),
                validation_status=ValidationStatus.NOT_CHECKED,
            )
            db.add(doc)
            db.flush()
            ids.append(doc.id)
        db.commit()
        return analyst.id, ids


def test_list_sorted_newest_first(client):
    analyst_id, _ = seed_analyst_with_docs(5)
    resp = client.get(f"/api/analysts/{analyst_id}/documents")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 5
    titles = [item["title"] for item in body["items"]]
    assert titles == ["Страница 5", "Страница 4", "Страница 3", "Страница 2", "Страница 1"]


def test_pagination(client):
    analyst_id, _ = seed_analyst_with_docs(5)
    page1 = client.get(f"/api/analysts/{analyst_id}/documents?page=1&page_size=2").json()
    page2 = client.get(f"/api/analysts/{analyst_id}/documents?page=2&page_size=2").json()
    assert page1["total"] == 5 and len(page1["items"]) == 2
    assert page1["items"][0]["title"] == "Страница 5"
    assert page2["items"][0]["title"] == "Страница 3"
    # 5 документов по 2 на страницу: третья страница содержит последний элемент
    page3 = client.get(f"/api/analysts/{analyst_id}/documents?page=3&page_size=2").json()
    assert len(page3["items"]) == 1 and page3["items"][0]["title"] == "Страница 1"
    # за пределами — пустой список, но не ошибка
    page4 = client.get(f"/api/analysts/{analyst_id}/documents?page=4&page_size=2").json()
    assert page4["items"] == []


def test_search_by_title(client):
    analyst_id, _ = seed_analyst_with_docs(5)
    body = client.get(f"/api/analysts/{analyst_id}/documents", params={"query": "СтРаНиЦа 3"}).json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Страница 3"


def test_search_by_url(client):
    analyst_id, _ = seed_analyst_with_docs(5)
    # полная ссылка с протоколом и хвостовым слэшэм
    full_url = "https://conf.test/pages/viewpage.action?pageId=1003/"
    body = client.get(f"/api/analysts/{analyst_id}/documents", params={"url": full_url}).json()
    assert body["total"] == 1
    assert body["items"][0]["confluence_page_id"] == "1003"


def test_combined_search_empty(client):
    analyst_id, _ = seed_analyst_with_docs(3)
    body = client.get(
        f"/api/analysts/{analyst_id}/documents",
        params={"query": "нет такого", "url": "conf.test"},
    ).json()
    assert body["total"] == 0 and body["items"] == []


def test_list_analyst_not_found(client):
    assert client.get("/api/analysts/999/documents").status_code == 404


def test_get_document_detail(client):
    analyst_id, doc_ids = seed_analyst_with_docs(2)
    resp = client.get(f"/api/documents/{doc_ids[0]}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["validation_status"] == "not_checked"
    assert body["analyst_id"] == analyst_id
    assert "<h1>Введение</h1>" in body["content_html"]
    assert client.get("/api/documents/99999").status_code == 404


def _global_search_seed() -> tuple[int, int]:
    """Два аналитика с документами, у которых пересекаются названия."""
    with SessionLocal() as db:
        first = Analyst(full_name="Первый", email="first@mts.ru")
        second = Analyst(full_name="Второй", email="second@mts.ru")
        db.add_all([first, second])
        db.flush()
        older = now_utc() - timedelta(days=10)
        newer = now_utc() - timedelta(hours=1)
        db.add_all(
            [
                ConfluenceDocument(
                    analyst_id=first.id,
                    confluence_page_id="2001",
                    title="[СТ] GDS-15 Загрузка кино",
                    url="https://conf.test/2001",
                    content_html="<h1>Введение</h1>",
                    last_modified_in_confluence_at=older,
                    validation_status=ValidationStatus.FAILED,
                ),
                ConfluenceDocument(
                    analyst_id=second.id,
                    confluence_page_id="2002",
                    title="GDS-15 ревью",
                    url="https://conf.test/2002",
                    content_html="<h1>Введение</h1>",
                    last_modified_in_confluence_at=newer,
                    validation_status=ValidationStatus.PASSED,
                ),
                ConfluenceDocument(
                    analyst_id=second.id,
                    confluence_page_id="2003",
                    title="Без совпадений",
                    url="https://conf.test/2003",
                    content_html="<h1>Введение</h1>",
                    last_modified_in_confluence_at=newer,
                    validation_status=ValidationStatus.NOT_CHECKED,
                ),
            ]
        )
        db.commit()
        return first.id, second.id


def test_global_search_across_analysts(client):
    _global_search_seed()
    body = client.get("/api/documents/search", params={"q": "gds-15"}).json()
    # регистр не важен, оба аналитика найдены, без совпадений — нет
    assert [hit["title"] for hit in body] == ["GDS-15 ревью", "[СТ] GDS-15 Загрузка кино"]
    assert body[0]["analyst_name"] == "Второй"
    assert body[0]["validation_status"] == "passed"
    assert all(hit["analyst_id"] for hit in body)


def test_global_search_short_query_returns_empty(client):
    _global_search_seed()
    assert client.get("/api/documents/search", params={"q": "g"}).json() == []
    assert client.get("/api/documents/search").json() == []


def test_global_search_limit(client):
    _global_search_seed()
    body = client.get("/api/documents/search", params={"q": "gds", "limit": 1}).json()
    assert len(body) == 1 and body[0]["title"] == "GDS-15 ревью"
