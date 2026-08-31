"""SSE-поток событий фоновых задач: GET /api/events.

UI подписывается один раз и узнаёт о запуске/завершении синхронизации
и проверок в момент события — без перезагрузки страницы. Авторизация —
сквозная basic-auth (обычный http-scope, middleware её закрывает).
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from starlette.responses import StreamingResponse

from app.usecase import tasks

router = APIRouter()

# Пустой комментарий раз в 20 c: соединение живо и прокси не рвёт его
# по read timeout, даже когда событий нет.
KEEPALIVE_SECONDS = 20.0


def format_event(event: dict) -> str:
    """Событие в кадре SSE: `event: <тип>\\ndata: <json>\\n\\n`."""
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.get("/api/events")
async def events() -> StreamingResponse:
    queue = tasks.subscribe_events()

    async def stream():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield format_event(event)
        finally:
            tasks.unsubscribe_events(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # страховка от буферизации прокси (nginx отключается и конфигом)
            "X-Accel-Buffering": "no",
        },
    )
