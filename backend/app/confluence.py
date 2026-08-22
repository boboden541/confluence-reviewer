"""Клиент Confluence Data Center/Server REST API (v1).

- Авторизация: Bearer PAT (confluence_auth_type=bearer) или Basic.
- Клиентский rate-limit: пауза между запросами (НФТ-CR-6, <= 10 req/s).
- Ретраи на 429/5xx.
"""

from __future__ import annotations

import asyncio
import html
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger("confluence_reviewer.confluence")

_RETRIES = 3
_TIMEOUT = httpx.Timeout(30.0, read=60.0)


class ConfluenceError(RuntimeError):
    """Ошибка обращения к Confluence (сеть, авторизация, 4xx/5xx)."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(slots=True)
class PageSummary:
    """Краткая информация о странице из поиска."""

    page_id: str
    title: str
    url: str
    created_at: datetime | None
    last_modified_at: datetime | None


@dataclass(slots=True)
class PageContent:
    """Полное содержимое страницы (body.storage)."""

    page_id: str
    title: str
    url: str
    content_html: str
    created_at: datetime | None
    last_modified_at: datetime | None


def parse_confluence_dt(value: str | None) -> datetime | None:
    """'2026-08-21T13:42:13.323+03:00' -> наивный UTC datetime; None при отсутствии."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def creator_candidates(email: str, override_username: str | None, mode: str) -> list[str]:
    """Кандидаты идентификатора автора для CQL creator=...

    БФТ 3.1 №13: сопоставление по email; фактически в DC username часто
    совпадает с локальной частью email, режим auto пробует оба.
    """
    local_part = email.split("@", 1)[0]
    if override_username:
        return [override_username]
    if mode == "email":
        return [email]
    if mode == "username":
        return [local_part]
    return [email, local_part]


class ConfluenceClient:
    """Тонкая обёртка над /rest/api Confluence."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        headers = {"Accept": "application/json", "User-Agent": "confluence-reviewer/1.0"}
        auth = None
        if settings.confluence_auth_type == "basic":
            auth = httpx.BasicAuth(
                settings.confluence_username or "", settings.confluence_password or ""
            )
        else:
            headers["Authorization"] = f"Bearer {settings.confluence_token}"
        self._client = httpx.AsyncClient(
            base_url=settings.confluence_base_url.rstrip("/"),
            headers=headers,
            auth=auth,
            timeout=_TIMEOUT,
            transport=transport,
            # Корпоративный корневой CA для внутреннего Confluence (если задан)
            verify=settings.confluence_ca_bundle or True,
        )

    async def __aenter__(self) -> "ConfluenceClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    # --- низкий уровень ---

    async def _throttle(self) -> None:
        if self._settings.confluence_request_delay > 0:
            await asyncio.sleep(self._settings.confluence_request_delay)

    async def _request(
        self, method: str, path: str, *, params: dict | None = None, json_body: dict | None = None
    ) -> Any:
        if not self._settings.confluence_base_url:
            raise ConfluenceError("CONFLUENCE_BASE_URL не настроен")

        last_error: Exception | None = None
        for attempt in range(1, _RETRIES + 1):
            await self._throttle()
            try:
                resp = await self._client.request(method, path, params=params, json=json_body)
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("Сетевая ошибка Confluence (%s/3): %s", attempt, exc)
                await asyncio.sleep(attempt)
                continue

            if resp.status_code in (429, 500, 502, 503, 504) and attempt < _RETRIES:
                retry_after = float(resp.headers.get("Retry-After", attempt * 2))
                logger.warning(
                    "Confluence вернул %s (%s/3), пауза %ss", resp.status_code, attempt, retry_after
                )
                await asyncio.sleep(min(retry_after, 30))
                continue

            if resp.status_code >= 400:
                detail = ""
                try:
                    detail = resp.json().get("message", "")
                except Exception:  # noqa: BLE001
                    detail = resp.text[:200]
                raise ConfluenceError(
                    f"Confluence API {resp.status_code}: {detail or resp.reason_phrase}",
                    status_code=resp.status_code,
                )
            return resp.json()

        raise ConfluenceError(f"Confluence недоступен после {_RETRIES} попыток: {last_error}")

    # --- публичные методы ---

    async def search_pages(self, creator: str) -> list[PageSummary]:
        """Все страницы (type=page), созданные пользователем creator (CQL)."""
        cql = f'type=page AND creator="{creator}"'
        results: list[dict] = []
        start = 0
        limit = self._settings.confluence_page_size
        max_pages = self._settings.confluence_max_pages

        while True:
            payload = await self._request(
                "GET",
                "/rest/api/content/search",
                params={
                    "cql": cql,
                    "limit": limit,
                    "start": start,
                    "expand": "history,version",
                },
            )
            batch = payload.get("results", [])
            results.extend(batch)
            total = payload.get("totalSize", len(results))
            start += limit
            if not batch or start >= total or len(results) >= max_pages:
                break
        return [self._to_summary(item) for item in results]

    def _to_summary(self, item: dict) -> PageSummary:
        links = item.get("_links", {})
        webui = links.get("webui", "")
        history = item.get("history", {})
        return PageSummary(
            page_id=str(item["id"]),
            title=item.get("title", ""),
            url=self._page_url(webui, item["id"]),
            created_at=parse_confluence_dt(history.get("createdDate")),
            last_modified_at=parse_confluence_dt(
                history.get("lastUpdated", {}).get("when")
                or item.get("version", {}).get("when")
            ),
        )

    def _page_url(self, webui: str, page_id: str) -> str:
        base = self._settings.confluence_base_url.rstrip("/")
        if webui:
            return f"{base}{webui}"
        return f"{base}/pages/viewpage.action?pageId={page_id}"

    async def get_page(self, page_id: str) -> PageContent:
        """Полное содержимое страницы: body.storage + метаданные версии."""
        payload = await self._request(
            "GET",
            f"/rest/api/content/{page_id}",
            params={"expand": "body.storage,version,history"},
        )
        history = payload.get("history", {})
        last_modified_raw = (history.get("lastUpdated") or {}).get("when") or payload.get(
            "version", {}
        ).get("when")
        return PageContent(
            page_id=str(payload["id"]),
            title=payload.get("title", ""),
            url=self._page_url(payload.get("_links", {}).get("webui", ""), payload["id"]),
            content_html=payload.get("body", {}).get("storage", {}).get("value", ""),
            created_at=parse_confluence_dt(history.get("createdDate")),
            last_modified_at=parse_confluence_dt(last_modified_raw),
        )

    async def add_comment(self, page_id: str, text: str) -> None:
        """Опубликовать комментарий на странице (ФТ-CR-17)."""
        paragraphs = "".join(
            f"<p>{html.escape(line)}</p>" for line in text.split("\n") if line.strip()
        ) or f"<p>{html.escape(text)}</p>"
        await self._request(
            "POST",
            "/rest/api/content",
            json_body={
                "type": "comment",
                "container": {"type": "page", "id": str(page_id)},
                "body": {"storage": {"value": paragraphs, "representation": "storage"}},
            },
        )

    async def whoami(self) -> dict:
        """Проверка авторизации и формата username текущего пользователя."""
        return await self._request("GET", "/rest/api/user/current")
