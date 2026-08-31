"""Тесты basic-авторизации сервиса (НФТ-CR-7)."""

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


def test_no_credentials_401(auth_client):
    resp = auth_client.get("/api/analysts")
    assert resp.status_code == 401
    # Без WWW-Authenticate: иначе браузер рисует нативный диалог поверх SPA.
    assert "WWW-Authenticate" not in resp.headers


def test_wrong_password_401(auth_client):
    resp = auth_client.get("/api/analysts", auth=(USERNAME, "wrong"))
    assert resp.status_code == 401


def test_correct_credentials_200(auth_client):
    resp = auth_client.get("/api/analysts", auth=(USERNAME, PASSWORD))
    assert resp.status_code == 200


def test_health_open_without_auth(auth_client):
    assert auth_client.get("/api/health").status_code == 200


def test_malformed_authorization_header_401(auth_client):
    resp = auth_client.get(
        "/api/analysts", headers={"Authorization": "Basic not-base64!!"}
    )
    assert resp.status_code == 401


def test_empty_password_config_denies_all(empty_password_client):
    """Включённая авторизация с пустым паролем = всё запрещено (misconfiguration)."""
    resp = empty_password_client.get("/api/analysts", auth=(USERNAME, ""))
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
    assert auth_client.get("/docs", auth=(USERNAME, PASSWORD)).status_code == 200
    assert auth_client.get("/openapi.json", auth=(USERNAME, PASSWORD)).status_code == 200


def test_unknown_path_requires_auth(auth_client):
    """Неизвестный путь без учётки — 401 (паритет с middleware), с учёткой — 404."""
    assert auth_client.get("/api/no-such-endpoint").status_code == 401
    resp = auth_client.get("/api/no-such-endpoint", auth=(USERNAME, PASSWORD))
    assert resp.status_code == 404
