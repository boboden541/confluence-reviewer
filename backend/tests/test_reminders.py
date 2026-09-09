"""Тесты напоминаний: создание, личный список, статусная модель, удаление."""

from __future__ import annotations

from datetime import timedelta

from app.database import SessionLocal
from app.models import Analyst, ConfluenceDocument
from app.utils import now_utc

import pytest


def _analyst(**overrides) -> Analyst:
    data = {
        "full_name": "Алиев Рустам",
        "email": f"rem-{now_utc().timestamp()}-{id(object())}@company.ru",
    }
    data.update(overrides)
    with SessionLocal() as db:
        analyst = Analyst(**data)
        db.add(analyst)
        db.commit()
        db.refresh(analyst)
        return analyst


def _document(analyst_id: int, title: str = "Системные требования СМЭ") -> int:
    with SessionLocal() as db:
        doc = ConfluenceDocument(
            analyst_id=analyst_id,
            confluence_page_id=str(now_utc().timestamp()).replace(".", "") + str(id(object())),
            title=title,
            url="https://conf.test/x",
            content_html="<h1>Введение</h1>",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc.id


def _other_analyst() -> Analyst:
    return _analyst(full_name="Белышева Жанна")


# --- создание ---


def test_create_reminder_201(client):
    analyst = _analyst()
    resp = client.post(
        "/api/reminders",
        json={
            "analyst_id": analyst.id,
            "document_id": None,
            "text": "Проверить, что учёл комментарии по СМЭ",
            "remind_at": "2026-09-14T10:00:00",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["analyst_id"] == analyst.id
    assert body["analyst_name"] == analyst.full_name
    assert body["document_id"] is None
    assert body["status"] == "open"
    assert body["remind_at"] is not None


def test_create_with_document_binds_context(client):
    analyst = _analyst()
    doc_id = _document(analyst.id)
    resp = client.post(
        "/api/reminders",
        json={"analyst_id": analyst.id, "document_id": doc_id, "text": "вернуться", "remind_at": None},
    )
    body = resp.json()
    assert body["document_id"] == doc_id
    assert body["document_title"] == "Системные требования СМЭ"


def test_create_unknown_analyst_404(client):
    resp = client.post(
        "/api/reminders",
        json={"analyst_id": 999999, "text": "текст", "remind_at": None},
    )
    assert resp.status_code == 404


def test_create_document_of_other_analyst_422(client):
    analyst = _analyst()
    foreign = _other_analyst()
    foreign_doc = _document(foreign.id, "Чужой документ")
    resp = client.post(
        "/api/reminders",
        json={"analyst_id": analyst.id, "document_id": foreign_doc, "text": "текст", "remind_at": None},
    )
    assert resp.status_code == 422
    assert "не принадлежит" in resp.json()["detail"]


def test_create_empty_text_422(client):
    analyst = _analyst()
    resp = client.post(
        "/api/reminders",
        json={"analyst_id": analyst.id, "text": "", "remind_at": None},
    )
    assert resp.status_code == 422


# --- список: личный, сортировка ---


def test_list_returns_own_reminders(client):
    analyst = _analyst()
    mine = client.post(
        "/api/reminders",
        json={"analyst_id": analyst.id, "text": "моё напоминание", "remind_at": None},
    ).json()
    client.post(
        "/api/reminders",
        json={"analyst_id": analyst.id, "text": "второе моё", "remind_at": None},
    )

    body = client.get("/api/reminders").json()
    assert [r["text"] for r in body] == ["моё напоминание", "второе моё"]


def test_list_filter_by_analyst(client):
    a1, a2 = _analyst(), _analyst(full_name="Белышева Жанна")
    client.post("/api/reminders", json={"analyst_id": a1.id, "text": "про первого", "remind_at": None})
    client.post("/api/reminders", json={"analyst_id": a2.id, "text": "про второго", "remind_at": None})

    body = client.get(f"/api/reminders?analyst_id={a2.id}").json()
    assert len(body) == 1
    assert body[0]["text"] == "про второго"


def test_list_sorts_open_by_date_done_last(client):
    analyst = _analyst()
    later = client.post(
        "/api/reminders",
        json={"analyst_id": analyst.id, "text": "дальше",
              "remind_at": (now_utc() + timedelta(days=3)).isoformat()},
    ).json()
    overdue = client.post(
        "/api/reminders",
        json={"analyst_id": analyst.id, "text": "просрочено",
              "remind_at": (now_utc() - timedelta(days=1)).isoformat()},
    ).json()
    no_date = client.post(
        "/api/reminders", json={"analyst_id": analyst.id, "text": "без даты", "remind_at": None}
    ).json()
    done = client.post(
        "/api/reminders", json={"analyst_id": analyst.id, "text": "выполнено", "remind_at": None}
    ).json()
    client.post(f"/api/reminders/{done['id']}/done")

    body = client.get("/api/reminders").json()
    assert [r["text"] for r in body] == ["просрочено", "дальше", "без даты", "выполнено"]
    assert [r["status"] for r in body] == ["open", "open", "open", "done"]


# --- статусная модель ---


def test_done_then_reopen(client):
    analyst = _analyst()
    created = client.post(
        "/api/reminders", json={"analyst_id": analyst.id, "text": "задача", "remind_at": None}
    ).json()

    done = client.post(f"/api/reminders/{created['id']}/done").json()
    assert done["status"] == "done" and done["done_at"] is not None

    reopened = client.post(f"/api/reminders/{created['id']}/reopen").json()
    assert reopened["status"] == "open" and reopened["done_at"] is None


# --- удаление ---


def test_delete_open_409_done_204(client):
    analyst = _analyst()
    created = client.post(
        "/api/reminders", json={"analyst_id": analyst.id, "text": "задача", "remind_at": None}
    ).json()
    assert client.delete(f"/api/reminders/{created['id']}").status_code == 409

    client.post(f"/api/reminders/{created['id']}/done")
    assert client.delete(f"/api/reminders/{created['id']}").status_code == 204
    assert client.get("/api/reminders").json() == []
