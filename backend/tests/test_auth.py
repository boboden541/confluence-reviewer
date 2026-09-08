"""Тесты авторизации сервиса (НФТ-CR-7): Bearer-сессии, вход God."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

USERNAME = "boss"
PASSWORD = "s3cret-пароль"


@pytest.fixture()
def auth_client():
    settings = Settings(
        auth_enabled=True,
        app_username=USERNAME,
        app_password=PASSWORD,
        _env_file=None,
    )
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture()
def empty_password_client():
    settings = Settings(
        auth_enabled=True, app_username=USERNAME, app_password="", _env_file=None
    )
    with TestClient(create_app(settings)) as client:
        yield client


def _login(client: TestClient) -> dict:
    resp = client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def _login_headers(client: TestClient) -> dict:
    return _login(client)


def test_no_credentials_401(auth_client):
    resp = auth_client.get("/api/analysts")
    assert resp.status_code == 401
    # Без WWW-Authenticate: иначе браузер рисует нативный диалог поверх SPA.
    assert "WWW-Authenticate" not in resp.headers


def test_god_login_returns_session(auth_client):
    resp = auth_client.post(
        "/api/auth/login", json={"username": USERNAME, "password": PASSWORD}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"]
    assert body["user"]["full_name"]
    assert body["user"]["is_god"] is True
    assert "checks" in body["user"]["permissions"]


def test_wrong_password_401(auth_client):
    resp = auth_client.post(
        "/api/auth/login", json={"username": USERNAME, "password": "wrong"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Неверный логин или пароль"


def test_session_grants_access(auth_client):
    headers = _login_headers(auth_client)
    assert auth_client.get("/api/analysts", headers=headers).status_code == 200


def test_health_open_without_auth(auth_client):
    assert auth_client.get("/api/health").status_code == 200


def test_malformed_authorization_header_401(auth_client):
    resp = auth_client.get("/api/analysts", headers={"Authorization": "Bearer not-a-token!!"})
    assert resp.status_code == 401


def test_empty_password_config_denies_all(empty_password_client):
    """Включённая авторизация с пустым паролем = всё запрещено (misconfiguration)."""
    resp = empty_password_client.post(
        "/api/auth/login", json={"username": USERNAME, "password": ""}
    )
    assert resp.status_code == 401
    assert empty_password_client.get("/api/health").status_code == 200


def test_auth_disabled_allows_anonymous(client):
    """Обычный клиент conftest: AUTH_ENABLED=false — доступ без учётки."""
    assert client.get("/api/analysts").status_code == 200


def test_docs_require_auth(auth_client):
    """/docs и /openapi.json регистрируются мимо глобальной зависимости —
    закрываются перерегистрацией (dependencies.auth._protect_docs)."""
    assert auth_client.get("/docs").status_code == 401
    assert auth_client.get("/openapi.json").status_code == 401
    headers = _login_headers(auth_client)
    assert auth_client.get("/docs", headers=headers).status_code == 200
    assert auth_client.get("/openapi.json", headers=headers).status_code == 200


def test_unknown_path_requires_auth(auth_client):
    """Неизвестный путь без сессии — 401 (паритет с basic-этапом), с ней — 404."""
    assert auth_client.get("/api/no-such-endpoint").status_code == 401
    headers = _login_headers(auth_client)
    resp = auth_client.get("/api/no-such-endpoint", headers=headers)
    assert resp.status_code == 404


def test_logout_revokes_session(auth_client):
    headers = _login_headers(auth_client)
    assert auth_client.get("/api/analysts", headers=headers).status_code == 200
    assert auth_client.post("/api/auth/logout", headers=headers).status_code == 204
    assert auth_client.get("/api/analysts", headers=headers).status_code == 401


def test_me_describes_god(auth_client):
    headers = _login_headers(auth_client)
    body = auth_client.get("/api/auth/me", headers=headers).json()
    assert body["is_god"] is True
    assert body["role_name"] == "God"
    assert "moderation" in body["permissions"]
    assert "roles.manage" in body["permissions"]
