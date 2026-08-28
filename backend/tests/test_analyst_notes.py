"""Тесты markdown-заметки руководителя по аналитику (профиль аналитика)."""

from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Analyst, AnalystNote


def seed_analyst() -> int:
    with SessionLocal() as db:
        analyst = Analyst(full_name="Тест Профиль", email="anote@mts.ru")
        db.add(analyst)
        db.commit()
        return analyst.id


def test_note_empty_by_default(client):
    analyst_id = seed_analyst()
    resp = client.get(f"/api/analysts/{analyst_id}/note")
    assert resp.status_code == 200
    assert resp.json() == {
        "analyst_id": analyst_id,
        "content": "",
        "created_at": None,
        "updated_at": None,
    }


def test_note_create_and_read(client):
    analyst_id = seed_analyst()
    markdown = "## Профиль\n- сильные стороны: **декомпозиция**"
    resp = client.put(f"/api/analysts/{analyst_id}/note", json={"content": markdown})
    assert resp.status_code == 200
    body = resp.json()
    assert body["content"] == markdown
    assert body["created_at"] is not None

    assert client.get(f"/api/analysts/{analyst_id}/note").json()["content"] == markdown


def test_note_overwrite_keeps_single_row(client):
    analyst_id = seed_analyst()
    client.put(f"/api/analysts/{analyst_id}/note", json={"content": "первая"})
    first = client.get(f"/api/analysts/{analyst_id}/note").json()
    client.put(f"/api/analysts/{analyst_id}/note", json={"content": "вторая"})
    second = client.get(f"/api/analysts/{analyst_id}/note").json()
    assert second["content"] == "вторая"
    assert first["created_at"] == second["created_at"]  # та же запись, обновлённая
    assert second["updated_at"] >= first["updated_at"]


def test_note_delete_and_idempotency(client):
    analyst_id = seed_analyst()
    client.put(f"/api/analysts/{analyst_id}/note", json={"content": "заметка"})

    assert client.delete(f"/api/analysts/{analyst_id}/note").status_code == 204
    assert client.get(f"/api/analysts/{analyst_id}/note").json()["content"] == ""
    # повторное удаление пустой заметки — тоже 204
    assert client.delete(f"/api/analysts/{analyst_id}/note").status_code == 204


def test_unknown_analyst_404(client):
    for method in ("get", "put", "delete"):
        call = getattr(client, method)
        kwargs = {"json": {"content": "x"}} if method == "put" else {}
        resp = call("/api/analysts/999/note", **kwargs)
        assert resp.status_code == 404, method


def test_note_too_long_422(client):
    analyst_id = seed_analyst()
    resp = client.put(
        f"/api/analysts/{analyst_id}/note", json={"content": "x" * 100_001}
    )
    assert resp.status_code == 422


def test_note_removed_with_analyst(client):
    analyst_id = seed_analyst()
    client.put(f"/api/analysts/{analyst_id}/note", json={"content": "заметка"})
    assert client.delete(f"/api/analysts/{analyst_id}").status_code == 204
    with SessionLocal() as db:
        left = db.scalars(select(AnalystNote)).all()
        assert left == []  # каскад: заметка ушла вместе с аналитиком
