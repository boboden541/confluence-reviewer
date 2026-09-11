"""Тесты эндпоинтов ручного запуска синхронизации (ФТ-CR-6)."""

from __future__ import annotations

import asyncio

import pytest

from app.usecase import tasks
from app.usecase.sync import SyncResult


@pytest.fixture()
def fake_execute(monkeypatch):
    calls: list[int | None] = []

    async def fake(analyst_id, on_analyst=None):
        calls.append(analyst_id)
        return [SyncResult(analyst_id=analyst_id or 0, analyst_name="Тест", created=1, updated=0)]

    monkeypatch.setattr(tasks, "_execute_sync", fake)
    return calls


def _wait_finished(client, attempts: int = 50) -> dict:
    import time

    for _ in range(attempts):
        status = client.get("/api/sync/status").json()
        if not status["running"]:
            return status
        time.sleep(0.05)
    pytest.fail("Фоновая задача не завершилась за отведённое время")


def test_trigger_sync_all(client, fake_execute):
    resp = client.post("/api/sync/all")
    assert resp.status_code == 202
    status = _wait_finished(client)
    assert fake_execute == [None]  # проверяем после завершения: задача фоновая
    assert status["last_results"][0]["created"] == 1


def test_trigger_analyst_sync(client, fake_execute):
    analyst_id = client.post(
        "/api/analysts", json={"full_name": "Тест", "email": "t@mts.ru"}
    ).json()["id"]

    resp = client.post(f"/api/analysts/{analyst_id}/sync")
    assert resp.status_code == 202
    _wait_finished(client)
    assert fake_execute == [analyst_id]


def test_trigger_analyst_sync_not_found(client, fake_execute):
    assert client.post("/api/analysts/999/sync").status_code == 404


def test_trigger_while_running_conflict(client, fake_execute, monkeypatch):
    # имитация незавершённой задачи
    monkeypatch.setattr(tasks, "_sync_state", {**tasks.sync_status(), "running": True})
    resp = client.post("/api/sync/all")
    assert resp.status_code == 409


def test_sync_all_publishes_per_analyst_progress(client, monkeypatch):
    """Синхронизация всех публикует «текущего аналитика» перед каждым шагом:
    UI видит, кто именно обрабатывается прямо сейчас."""
    seen_current: list[dict | None] = []
    real_publish = tasks._publish_event

    def spy(event_type, payload):
        if event_type == "sync":
            seen_current.append(payload.get("current"))
        real_publish(event_type, payload)

    client.post("/api/analysts", json={"full_name": "Первый", "email": "p1@mts.ru"})
    client.post("/api/analysts", json={"full_name": "Второй", "email": "p2@mts.ru"})

    ids = [a["id"] for a in client.get("/api/analysts").json()]

    async def fake(analyst_id, on_analyst=None):
        # имитация sync_all: перебрать аналитиков, отчитаться прогрессом
        for index, aid in enumerate(analyst_id if analyst_id is not None else ids, start=1):
            if on_analyst is not None:
                await on_analyst(aid, f"Аналитик {aid}", index, len(ids))
        return [SyncResult(analyst_id=aid, analyst_name="A", created=0, updated=0) for aid in ids]

    monkeypatch.setattr(tasks, "_execute_sync", fake)
    monkeypatch.setattr(tasks, "_publish_event", spy)

    client.post("/api/sync/all")
    for _ in range(50):
        if not tasks.sync_status()["running"]:
            break
        import time

        time.sleep(0.05)

    status = tasks.sync_status()
    assert status["current"] is None  # после завершения указатель снят
    # перед каждым аналитиком было событие с current (1-й и 2-й)
    current_events = [c for c in seen_current if c]
    assert [c["index"] for c in current_events] == [1, 2]
    assert current_events[0]["total"] == 2
    # имена — «Аналитик {id}» из стаба, порядок соответствует порядку аналитиков
    assert [c["analyst_name"] for c in current_events] == [f"Аналитик {i}" for i in ids]
