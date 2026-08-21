"""Тесты эндпоинтов ручного запуска синхронизации (ФТ-CR-6)."""

from __future__ import annotations

import asyncio

import pytest

from app.services import tasks
from app.services.sync import SyncResult


@pytest.fixture()
def fake_execute(monkeypatch):
    calls: list[int | None] = []

    async def fake(analyst_id):
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
    assert fake_execute == [None]
    status = _wait_finished(client)
    assert status["last_results"][0]["created"] == 1


def test_trigger_analyst_sync(client, fake_execute):
    analyst_id = client.post(
        "/api/analysts", json={"full_name": "Тест", "email": "t@mts.ru"}
    ).json()["id"]

    resp = client.post(f"/api/analysts/{analyst_id}/sync")
    assert resp.status_code == 202
    assert fake_execute == [analyst_id]


def test_trigger_analyst_sync_not_found(client, fake_execute):
    assert client.post("/api/analysts/999/sync").status_code == 404


def test_trigger_while_running_conflict(client, fake_execute, monkeypatch):
    # имитация незавершённой задачи
    monkeypatch.setattr(tasks, "_sync_state", {**tasks.sync_status(), "running": True})
    resp = client.post("/api/sync/all")
    assert resp.status_code == 409
