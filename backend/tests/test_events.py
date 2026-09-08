"""События фоновых задач для UI: pub/sub и SSE-стрим /api/events.

Starlette TestClient прогоняет приложение до конца ответа — бесконечный
SSE-генератор в нём зависает, поэтому стрим проверяется на живом uvicorn
(отдельный поток, свободный порт). Pub/sub и формат кадра — юнит-тесты.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from types import SimpleNamespace

import httpx
import uvicorn

from app.database import Base, SessionLocal, engine
from app.main import create_app
from app.models import Analyst, ConfluenceDocument
from app.api.events import format_event
from app.usecase import tasks
from app.usecase.validation import _UNSET
from app.utils import now_utc

import pytest


@pytest.fixture(autouse=True)
def _db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def live_server():
    """Живой uvicorn на свободном порту: настоящий SSE-стрим по TCP."""
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=0, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):  # ждём принятия соединений
        if server.started:
            break
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def seed_document() -> int:
    with SessionLocal() as db:
        analyst = Analyst(full_name="События", email=f"ev-{now_utc().timestamp()}@mts.ru")
        db.add(analyst)
        db.flush()
        doc = ConfluenceDocument(
            analyst_id=analyst.id,
            confluence_page_id=str(now_utc().timestamp()).replace(".", ""),
            title="[СТ] Документ",
            url="https://conf.test/pages/ev",
            content_html="<h1>Введение</h1>",
            last_modified_in_confluence_at=now_utc(),
        )
        db.add(doc)
        db.commit()
        return doc.id


def read_events(resp, count: int) -> list[dict]:
    """Прочитать `count` кадров SSE из открытого стрима."""
    events: list[dict] = []
    event_type = ""
    for line in resp.iter_lines():
        if line.startswith("event:"):
            event_type = line[len("event:"):].strip()
        elif line.startswith("data:"):
            payload = json.loads(line[len("data:"):].strip())
            assert payload["type"] == event_type
            events.append(payload)
            if len(events) == count:
                return events
    raise AssertionError(f"стрим закрылся раньше {count} событий: получено {len(events)}")


def wait_no_subscribers(timeout_s: float = 3.0) -> None:
    """Клиент отключился — сервер убрал очередь подписчика (асинхронно)."""
    deadline = time.monotonic() + timeout_s
    while tasks._event_subscribers and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not tasks._event_subscribers


# --- юнит: pub/sub и формат кадра ---


def test_format_event_frame():
    frame = format_event(
        {"type": "validation", "status": "done", "at": "2026-09-08T12:00:00"}
    )
    # событие несёт момент публикации (журнал ленты) — он уходит в кадр как есть
    assert frame == (
        'event: validation\ndata: {"type": "validation", "status": "done", '
        '"at": "2026-09-08T12:00:00"}\n\n'
    )


def test_subscribe_snapshot_and_publish():
    """Подписка даёт снимок sync+bulk; дальше приходят только публикации."""
    async def scenario() -> None:
        queue = tasks.subscribe_events()
        assert queue.get_nowait()["type"] == "sync"
        assert queue.get_nowait()["type"] == "bulk"

        tasks._publish_event("validation", {"document_id": 5, "status": "done"})
        event = queue.get_nowait()
        event.pop("at")  # момент публикации добавлен журналом ленты
        assert event == {"type": "validation", "document_id": 5, "status": "done"}

        tasks.unsubscribe_events(queue)
        tasks._publish_event("sync", {"running": False})
        assert queue.empty()  # отписанный больше не получает

    asyncio.run(scenario())


# --- интеграция: живой сервер ---


def test_stream_headers_and_snapshot(live_server):
    """Подключение: заголовки SSE + снимок состояний sync и bulk."""
    with httpx.stream("GET", f"{live_server}/api/events", timeout=10) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers["cache-control"] == "no-cache"

        snapshot = read_events(resp, 2)
        assert [e["type"] for e in snapshot] == ["sync", "bulk"]
        assert snapshot[0]["running"] is False
        assert snapshot[1]["running"] is False
    wait_no_subscribers()


def test_validation_lifecycle_streamed(live_server, monkeypatch):
    """Одиночная проверка: события running и done с report_id приходят в стрим."""
    doc_id = seed_document()

    async def fake_exec(document_id, trigger, force, template_version_id=None,
                        ai_prompt=None, checks=None, criterion_ids=None,
                        ai_connection=_UNSET, owner_user=None):
        return SimpleNamespace(id=77)

    monkeypatch.setattr(tasks, "_execute_validation", fake_exec)

    with httpx.stream("GET", f"{live_server}/api/events", timeout=10) as resp:
        assert httpx.post(f"{live_server}/api/documents/{doc_id}/validate").status_code == 202

        events = read_events(resp, 4)
        assert [e["type"] for e in events] == ["sync", "bulk", "validation", "validation"]
        running, done = events[2], events[3]
        assert running["document_id"] == doc_id
        assert running["status"] == "running"
        assert done["status"] == "done"
        assert done["report_id"] == 77


def test_bulk_events_for_valid_docs(live_server, monkeypatch):
    """Массовая проверка: прогресс bulk растёт, финал running=False."""
    first, second = seed_document(), seed_document()
    seen: list[int] = []

    async def fake_exec(document_id, trigger, force, template_version_id=None,
                        ai_prompt=None, checks=None, criterion_ids=None, **_kwargs):
        seen.append(document_id)
        return SimpleNamespace(id=document_id)

    monkeypatch.setattr(tasks, "_execute_validation", fake_exec)

    with httpx.stream("GET", f"{live_server}/api/events", timeout=10) as resp:
        assert (
            httpx.post(
                f"{live_server}/api/documents/validate-batch",
                json={"document_ids": [first, second]},
            ).status_code
            == 202
        )
        # снимки(2) + bulk старт + [валидация×2 + bulk прогресс]×2 + bulk финал
        events = read_events(resp, 10)
        assert [e["type"] for e in events] == [
            "sync", "bulk", "bulk",
            "validation", "validation", "bulk",
            "validation", "validation", "bulk", "bulk",
        ]
        assert events[2]["running"] is True
        assert events[2]["total"] == 2
        assert events[5]["done"] == 1
        assert events[8]["running"] is True  # последний документ готов…
        assert events[8]["done"] == 2
        assert events[9]["running"] is False  # …и только затем прогон закрыт
        assert seen == [first, second]


def test_sync_lifecycle_streamed(live_server, monkeypatch):
    """Синхронизация: running/finished с итогами по аналитикам."""
    with SessionLocal() as db:
        db.add(Analyst(full_name="Синк", email=f"sync-ev-{now_utc().timestamp()}@mts.ru"))
        db.commit()
        analyst_id = db.query(Analyst).first().id

    async def fake_execute(analyst_id_arg):
        return [
            tasks.SyncResult(
                analyst_id=analyst_id_arg, analyst_name="Синк", created=3, updated=2
            )
        ]

    monkeypatch.setattr(tasks, "_execute_sync", fake_execute)

    with httpx.stream("GET", f"{live_server}/api/events", timeout=10) as resp:
        assert httpx.post(f"{live_server}/api/analysts/{analyst_id}/sync").status_code == 202

        events = read_events(resp, 4)
        assert [e["type"] for e in events] == ["sync", "bulk", "sync", "sync"]
        assert events[2]["running"] is True
        assert events[3]["running"] is False
        assert events[3]["last_results"] == [
            {"analyst_id": analyst_id, "analyst_name": "Синк",
             "created": 3, "updated": 2, "error": None}
        ]


def test_keepalive_comment_when_idle(live_server, monkeypatch):
    """Без событий стрим шлёт keepalive-комментарий — соединение живо."""
    from app.api import events as events_router

    monkeypatch.setattr(events_router, "KEEPALIVE_SECONDS", 0.05)

    with httpx.stream("GET", f"{live_server}/api/events", timeout=10) as resp:
        for line in resp.iter_lines():
            if line == ": keepalive":
                return
    raise AssertionError("keepalive не получен")
