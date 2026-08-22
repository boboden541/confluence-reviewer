"""Тесты клиента Confluence на мок-транспорте httpx."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.config import Settings
from app.confluence import ConfluenceClient, ConfluenceError, creator_candidates


def make_settings(**overrides) -> Settings:
    values = dict(
        database_url="sqlite://",
        confluence_base_url="https://conf.test",
        confluence_auth_type="bearer",
        confluence_token="tok",
        confluence_page_size=2,
        confluence_max_pages=10,
        confluence_request_delay=0,
    )
    values.update(overrides)
    return Settings(**values)


def page_item(pid: str, title: str) -> dict:
    return {
        "id": pid,
        "title": title,
        "_links": {"webui": f"/display/MTSLIVE/{title}"},
        "history": {
            "createdDate": "2026-05-19T12:59:53.915+03:00",
            "lastUpdated": {"when": "2026-08-21T13:42:13.323+03:00"},
        },
    }


def run(coro):
    return asyncio.run(coro)


def test_creator_candidates_modes():
    assert creator_candidates("a@mts.ru", None, "email") == ["a@mts.ru"]
    assert creator_candidates("a@mts.ru", None, "username") == ["a"]
    assert creator_candidates("a@mts.ru", None, "auto") == ["a@mts.ru", "a"]
    # override имеет приоритет (БФТ 3.1 №13)
    assert creator_candidates("a@mts.ru", "custom", "auto") == ["custom"]


def test_bearer_auth_header_and_whoami():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"username": "raaliev"})

    async def scenario():
        async with ConfluenceClient(make_settings(), transport=httpx.MockTransport(handler)) as c:
            return await c.whoami()

    assert run(scenario())["username"] == "raaliev"
    assert captured["auth"] == "Bearer tok"


def test_search_pages_pagination():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params.get("start"))
        start = int(request.url.params.get("start"))
        if start == 0:
            return httpx.Response(
                200, json={"results": [page_item("1", "A"), page_item("2", "B")], "totalSize": 3}
            )
        return httpx.Response(200, json={"results": [page_item("3", "C")], "totalSize": 3})

    async def scenario():
        async with ConfluenceClient(make_settings(), transport=httpx.MockTransport(handler)) as c:
            return await c.search_pages("raaliev")

    pages = run(scenario())
    assert [p.page_id for p in pages] == ["1", "2", "3"]
    assert calls == ["0", "2"]
    assert pages[0].url == "https://conf.test/display/MTSLIVE/A"
    assert pages[0].created_at is not None and pages[0].created_at.year == 2026
    assert pages[0].last_modified_at.month == 8


def test_get_page_content():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "body.storage" in request.url.params.get("expand", "")
        return httpx.Response(
            200,
            json={
                "id": "2380439645",
                "title": "[СТ] Документ",
                "_links": {"webui": "/pages/viewpage.action?pageId=2380439645"},
                "body": {"storage": {"value": "<h1>Введение</h1><p>Текст</p>"}},
                "history": {"createdDate": "2026-05-19T12:59:53.915+03:00", "lastUpdated": None},
                "version": {"when": "2026-08-21T13:42:13.323+03:00"},
            },
        )

    async def scenario():
        async with ConfluenceClient(make_settings(), transport=httpx.MockTransport(handler)) as c:
            return await c.get_page("2380439645")

    page = run(scenario())
    assert page.title == "[СТ] Документ"
    assert "<h1>Введение</h1>" in page.content_html
    assert page.last_modified_at is not None


def test_add_comment_payload():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "999"})

    async def scenario():
        async with ConfluenceClient(make_settings(), transport=httpx.MockTransport(handler)) as c:
            await c.add_comment("123", "Строка 1\n<b>не html</b>")

    run(scenario())
    assert captured["method"] == "POST"
    body = captured["json"]
    assert body["type"] == "comment"
    assert body["container"] == {"type": "page", "id": "123"}
    storage = body["body"]["storage"]
    assert storage["representation"] == "storage"
    assert "&lt;b&gt;не html&lt;/b&gt;" in storage["value"]  # экранирование


def test_error_mapping_401():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Unauthorized"})

    async def scenario():
        async with ConfluenceClient(make_settings(), transport=httpx.MockTransport(handler)) as c:
            await c.whoami()

    with pytest.raises(ConfluenceError) as exc_info:
        run(scenario())
    assert exc_info.value.status_code == 401


def test_missing_base_url():
    async def scenario():
        async with ConfluenceClient(make_settings(confluence_base_url="")) as c:
            await c.whoami()

    with pytest.raises(ConfluenceError):
        run(scenario())


def test_ca_bundle_is_passed_to_ssl_verification():
    """CONFLUENCE_CA_BUNDLE попадает в проверку сертификатов httpx.

    httpx валидирует `verify` при создании транспорта: несуществующий путь
    к PEM-бандлу должен приводить к ошибке, корректный — приниматься.
    """
    import certifi

    # корректный PEM-бандл — клиент создаётся без ошибок
    client = ConfluenceClient(make_settings(confluence_ca_bundle=certifi.where()))
    assert isinstance(client._client, httpx.AsyncClient)
    asyncio.run(client.close())

    # несуществующий путь — ошибка на этапе построения SSL-контекста
    with pytest.raises(Exception):  # noqa: B017 — тип зависит от версии httpx
        ConfluenceClient(make_settings(confluence_ca_bundle="/no/such/bundle.pem"))
