"""Тесты markdown-заметок руководителя по документу (ФТ-CR-18)."""

from __future__ import annotations

from app.database import SessionLocal
from app.models import Analyst, ConfluenceDocument


def seed_doc() -> int:
    with SessionLocal() as db:
        analyst = Analyst(full_name="Тест", email="note@mts.ru")
        db.add(analyst)
        db.flush()
        doc = ConfluenceDocument(
            analyst_id=analyst.id,
            confluence_page_id="777001",
            title="[СТ] Документ",
            url="https://conf.test/p/777001",
            content_html="<h1>Введение</h1>",
        )
        db.add(doc)
        db.commit()
        return doc.id


def test_note_empty_by_default(client):
    doc_id = seed_doc()
    resp = client.get(f"/api/documents/{doc_id}/note")
    assert resp.status_code == 200
    assert resp.json() == {
        "document_id": doc_id,
        "content": "",
        "created_at": None,
        "updated_at": None,
    }


def test_note_create_and_read(client):
    doc_id = seed_doc()
    markdown = "## Ревью\n- уточнить **критерии приёмки** у аналитика"
    resp = client.put(f"/api/documents/{doc_id}/note", json={"content": markdown})
    assert resp.status_code == 200
    body = resp.json()
    assert body["content"] == markdown
    assert body["created_at"] is not None

    assert client.get(f"/api/documents/{doc_id}/note").json()["content"] == markdown


def test_note_overwrite_keeps_single_row(client):
    doc_id = seed_doc()
    client.put(f"/api/documents/{doc_id}/note", json={"content": "первая"})
    first = client.get(f"/api/documents/{doc_id}/note").json()
    client.put(f"/api/documents/{doc_id}/note", json={"content": "вторая"})
    second = client.get(f"/api/documents/{doc_id}/note").json()
    assert second["content"] == "вторая"
    assert first["created_at"] == second["created_at"]  # та же запись, обновлённая
    assert second["updated_at"] >= first["updated_at"]


def test_note_can_be_cleared(client):
    doc_id = seed_doc()
    client.put(f"/api/documents/{doc_id}/note", json={"content": "текст"})
    resp = client.put(f"/api/documents/{doc_id}/note", json={"content": ""})
    assert resp.status_code == 200
    assert client.get(f"/api/documents/{doc_id}/note").json()["content"] == ""


def test_note_document_not_found(client):
    assert client.get("/api/documents/99999/note").status_code == 404
    resp = client.put("/api/documents/99999/note", json={"content": "x"})
    assert resp.status_code == 404


def test_note_too_long_rejected(client):
    doc_id = seed_doc()
    resp = client.put(f"/api/documents/{doc_id}/note", json={"content": "x" * 100_001})
    assert resp.status_code == 422
