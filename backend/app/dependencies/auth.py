"""Аутентификация по Bearer-сессиям и проверка прав.

Сессии выдаёт /api/auth/login (God: логин+пароль из env) и
/api/auth/token-login (лид: персональный токен Confluence). При
AUTH_ENABLED=false сервис работает без авторизации: user=None,
права не проверяются, владелец нового контента — God (resolve_actor).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, Request
from starlette.responses import PlainTextResponse

from app.dependencies.db import get_db
from app.usecase import auth as auth_uc

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models import User

# Доступны без сессии: здоровье и сами входы
OPEN_PATHS = {
    "/api/health",
    "/api/auth/login",
    "/api/auth/token-login",
    "/api/auth/reapply",
}
_DOCS_PATHS = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
_CATCH_ALL_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]


class AuthRequiredError(Exception):
    """Нет/просрочена сессия (api-слой → 401 PlainText, паритет с Basic)."""


async def require_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Зависимость уровня приложения: кладёт текущего пользователя.

    Возвращает None только когда авторизация выключена (тесты/локально) —
    тогда права не проверяются, а владелец нового контента — God.
    """
    if not request.app.state.auth.get("enabled"):
        return None
    if request.url.path in OPEN_PATHS:
        return None
    user = _user_for_request(request, db)
    if user is None:
        raise AuthRequiredError()
    return user


def _user_for_request(request: Request, db: Session) -> User | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return auth_uc.user_for_session(db, auth.removeprefix("Bearer ").strip())


def resolve_actor(db: Session, user: User | None) -> User:
    """Владелец нового контента: текущий пользователь, при выключенной
    авторизации — God (единственный до одобрения заявок)."""
    if user is not None:
        return user
    from sqlalchemy import select

    from app.models import Role, User as UserModel

    god = db.scalar(select(UserModel).join(Role).where(Role.is_system.is_(True)).limit(1))
    if god is None:  # seed_auth ещё не выполнялся (юнит-тесты без lifespan)
        raise AuthRequiredError()
    return god


def require_permission(key: str):
    """Фабрика зависимостей: пользователь с правом key (или disabled)."""

    def _dependency(user: User | None = Depends(require_user)) -> User | None:
        try:
            auth_uc.ensure_permission(user, key)
        except auth_uc.PermissionDenied as exc:
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return user

    return _dependency


# ── документация и catch-all (как раньше, с новой зависимостью) ──────


def _auth_required_handler(request: Request, exc: Exception) -> PlainTextResponse:
    return PlainTextResponse("Требуется авторизация", status_code=401)


def _protect_docs(app: "FastAPI") -> None:
    """Перерегистрировать маршруты документации как APIRoute с авторизацией
    (старый механизм с этапа basic-auth, зависимость сменена на require_user)."""
    from fastapi.routing import APIRoute
    from fastapi import Depends

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
                    dependencies=[Depends(require_user)],
                )
            )
    app.router.routes.extend(protected)


def add_catch_all(app) -> None:
    """Неизвестные пути: 404, но после авторизации (паритет с Basic-этапом)."""
    from fastapi import HTTPException

    def _not_found():
        raise HTTPException(status_code=404)

    app.add_api_route(
        "/{full_path:path}",
        _not_found,
        methods=_CATCH_ALL_METHODS,
        include_in_schema=False,
        dependencies=[Depends(require_user)],
    )


def install_auth(app, settings: Settings) -> None:
    """Состояние авторизации: включена ли и учётка God (вход по паролю)."""
    app.state.auth = {
        "enabled": bool(settings.auth_enabled),
        "username": settings.app_username,
        "password": settings.app_password,
    }
    app.add_exception_handler(AuthRequiredError, _auth_required_handler)
    _protect_docs(app)
