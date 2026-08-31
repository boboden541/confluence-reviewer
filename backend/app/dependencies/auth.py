"""Basic-авторизация доступа к сервису (НФТ-CR-7) как FastAPI-зависимость.

Включается AUTH_ENABLED=true; учётка — APP_USERNAME / APP_PASSWORD из окружения.
install_auth кладёт эффективные параметры в app.state.auth (а не читает
get_settings в самой зависимости — create_app может получить другие Settings),
require_basic_auth вешается на приложение глобально и закрывает все маршруты,
кроме /api/health (он нужен контейнерным healthcheck'ам и ничего не раскрывает).

Защита от неверной конфигурации: если авторизация включена, но пароль пуст,
все запросы (кроме health) отклоняются.

Два места, куда глобальные dependencies FastAPI не дотягиваются, закрываются
отдельно (см. install_auth):
- /docs, /redoc, /openapi.json регистрируются через starlette add_route —
  для них маршруты перерегистрируются как APIRoute с той же зависимостью;
- неизвестные пути (404) — catch-all маршрут в конце таблицы маршрутов.
"""

from __future__ import annotations

import base64
import binascii
import secrets
from types import SimpleNamespace

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from fastapi.routing import APIRoute

OPEN_PATHS = {"/api/health"}

# Маршруты документации: setup() FastAPI добавляет их как starlette-маршруты,
# на которые app-level dependencies не действуют
_DOCS_PATHS = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}

# Catch-all закрывает и неизвестные пути: без авторизации они отдают 404
_CATCH_ALL_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]


class AuthRequiredError(Exception):
    """Нет или неверные учётные данные → 401 текстом без WWW-Authenticate."""


async def require_basic_auth(request: Request) -> None:
    """Глобальная зависимость: проверить Authorization: Basic … на каждом запросе."""
    auth = getattr(request.app.state, "auth", None)
    if auth is None or not auth.enabled:
        return
    if request.url.path in OPEN_PATHS:
        return
    if auth.password and _check_credentials(request.headers, auth.username, auth.password):
        return
    raise AuthRequiredError()


def _check_credentials(headers, username: str, password: str) -> bool:
    scheme, _, param = headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        decoded = base64.b64decode(param.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    got_username, _, got_password = decoded.partition(":")
    # compare_digest не принимает не-ASCII строки — сравниваем байты UTF-8
    return secrets.compare_digest(
        got_username.encode("utf-8"), username.encode("utf-8")
    ) and secrets.compare_digest(got_password.encode("utf-8"), password.encode("utf-8"))


def _auth_required_handler(_request: Request, _exc: AuthRequiredError) -> PlainTextResponse:
    # Без WWW-Authenticate: SPA имеет собственную форму входа, а заголовок
    # заставляет браузер рисовать нативный диалог поверх приложения.
    return PlainTextResponse("Требуется авторизация", status_code=401)


def _not_found() -> None:
    raise HTTPException(status_code=404, detail="Not Found")


def _protect_docs(app: FastAPI) -> None:
    """Перерегистрировать маршруты документации как APIRoute с авторизацией."""
    protected: list[APIRoute] = []
    for route in list(app.router.routes):
        if getattr(route, "path", None) in _DOCS_PATHS and not isinstance(route, APIRoute):
            app.router.routes.remove(route)
            protected.append(
                APIRoute(
                    route.path,
                    route.endpoint,
                    name=route.name,
                    include_in_schema=False,
                    dependencies=[Depends(require_basic_auth)],
                )
            )
    app.router.routes.extend(protected)


def install_auth(app: FastAPI, settings) -> None:
    """Положить параметры авторизации в app.state и закрыть документацию.

    Вызывается из create_app сразу после создания приложения: глобальная
    зависимость require_basic_auth уже объявлена в конструкторе FastAPI,
    сюда остаётся только конфигурация и нестандартные маршруты.
    """
    app.state.auth = SimpleNamespace(
        enabled=bool(settings.auth_enabled),
        username=settings.app_username,
        password=settings.app_password,
    )
    app.add_exception_handler(AuthRequiredError, _auth_required_handler)
    _protect_docs(app)


def add_catch_all(app: FastAPI) -> None:
    """Неизвестные пути тоже требуют авторизации (паритет с middleware).

    Вызывается ПОСЛЕ всех include_router: catch-all матчит любой путь и
    должен стоять в таблице маршрутов последним, иначе перекроет API.
    """
    app.add_api_route(
        "/{full_path:path}",
        _not_found,
        methods=_CATCH_ALL_METHODS,
        include_in_schema=False,
    )
