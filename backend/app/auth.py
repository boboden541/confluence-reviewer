"""Basic-авторизация доступа к сервису (НФТ-CR-7).

Включается AUTH_ENABLED=true; учётка — APP_USERNAME / APP_PASSWORD из окружения.
Реализовано как ASGI-middleware: закрывает все маршруты, кроме /api/health
(он нужен контейнерным healthcheck'ам и ничего не раскрывает).

Защита от неверной конфигурации: если авторизация включена, но пароль пуст,
все запросы (кроме health) отклоняются.
"""

from __future__ import annotations

import base64
import binascii
import secrets

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

OPEN_PATHS = {"/api/health"}


class BasicAuthMiddleware:
    """Проверка Authorization: Basic … на каждом HTTP-запросе."""

    def __init__(self, app: ASGIApp, username: str, password: str):
        self.app = app
        self._username = username
        self._password = password

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope.get("path") in OPEN_PATHS:
            await self.app(scope, receive, send)
            return

        if self._password and self._check_credentials(Headers(scope=scope)):
            await self.app(scope, receive, send)
            return

        # Без WWW-Authenticate: SPA имеет собственную форму входа, а заголовок
        # заставляет браузер рисовать нативный диалог поверх приложения.
        response = PlainTextResponse("Требуется авторизация", status_code=401)
        await response(scope, receive, send)

    def _check_credentials(self, headers: Headers) -> bool:
        scheme, _, param = headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "basic":
            return False
        try:
            decoded = base64.b64decode(param.strip(), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return False
        username, _, password = decoded.partition(":")
        # compare_digest не принимает не-ASCII строки — сравниваем байты UTF-8
        return secrets.compare_digest(
            username.encode("utf-8"), self._username.encode("utf-8")
        ) and secrets.compare_digest(
            password.encode("utf-8"), self._password.encode("utf-8")
        )
