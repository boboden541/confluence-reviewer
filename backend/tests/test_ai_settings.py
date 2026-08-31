"""Настройки подключения ИИ: GET/PUT с маскированием токена, тест связи.

Охватывает: env-дефолты без строки, семантику api_key (None/""/строка),
нормализацию URL, 422, приоритет «форма → сохранённое → env» в /test.
"""

from __future__ import annotations

import pytest

from app.database import SessionLocal
from app.models import AIConnectionSettings
from app.usecase.ai_settings import mask_api_key
from app.clients.ai_validator import AIValidationError


class FakeValidator:
    """Ловит эффективное подключение; ping управляется тестом."""

    last = None
    error: AIValidationError | None = None

    def __init__(self, connection=None, **kwargs):
        type(self).last = connection

    def ping(self):
        if type(self).error is not None:
            raise type(self).error
        return "Модель fake ответила"


@pytest.fixture()
def fake_validator(monkeypatch):
    FakeValidator.last = None
    FakeValidator.error = None
    monkeypatch.setattr("app.routers.ai_settings.AIValidator", FakeValidator)
    return FakeValidator


# --- GET: env-дефолты, пока ничего не сохранено ---


def test_get_returns_env_defaults_when_no_row(client):
    body = client.get("/api/ai-settings").json()
    assert body["protocol"] == "anthropic"
    assert body["base_url"] == "" and body["model"] == ""
    assert body["api_key_masked"] == ""
    assert body["updated_at"] is None
    assert body["env"]["api_key_set"] is True
    assert body["env"]["model"] == "glm-4.5"


# --- PUT: сохранение, маскирование, семантика api_key ---


def test_put_saves_and_masks_token(client):
    resp = client.put(
        "/api/ai-settings",
        json={
            "protocol": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o",
            "api_key": "sk-super-secret-token",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["protocol"] == "openai"
    assert body["base_url"] == "https://api.openai.com/v1"
    assert body["model"] == "gpt-4o"
    assert body["api_key_masked"] == "sk-…ken"
    assert body["updated_at"] is not None

    # открытый токен не появляется нигде в теле ответа
    assert "sk-super-secret-token" not in client.get("/api/ai-settings").text


def test_put_null_keeps_existing_token(client):
    client.put(
        "/api/ai-settings",
        json={"protocol": "openai", "base_url": "https://x.test/v1", "model": "m1",
              "api_key": "sk-first-secret-value"},
    )
    body = client.put(
        "/api/ai-settings",
        json={"protocol": "anthropic", "base_url": "", "model": "", "api_key": None},
    ).json()
    assert body["api_key_masked"] == "sk-…lue"  # ключ не тронут
    with SessionLocal() as db:
        assert db.get(AIConnectionSettings, 1).api_key == "sk-first-secret-value"


def test_put_empty_string_clears_token(client):
    client.put(
        "/api/ai-settings",
        json={"protocol": "anthropic", "base_url": "", "model": "",
              "api_key": "sk-first-secret-value"},
    )
    body = client.put(
        "/api/ai-settings",
        json={"protocol": "anthropic", "base_url": "", "model": "", "api_key": ""},
    ).json()
    assert body["api_key_masked"] == ""
    with SessionLocal() as db:
        assert db.get(AIConnectionSettings, 1).api_key == ""


def test_put_normalizes_base_url(client):
    body = client.put(
        "/api/ai-settings",
        json={"protocol": "openai", "base_url": "  https://x.test/v1/  ", "model": "m"},
    ).json()
    assert body["base_url"] == "https://x.test/v1"


def test_put_invalid_protocol_422(client):
    resp = client.put("/api/ai-settings", json={"protocol": "grpc", "base_url": "", "model": ""})
    assert resp.status_code == 422


def test_put_invalid_url_422(client):
    resp = client.put(
        "/api/ai-settings", json={"protocol": "openai", "base_url": "ftp://x.test", "model": "m"}
    )
    assert resp.status_code == 422


def test_put_blank_model_422(client):
    resp = client.put(
        "/api/ai-settings", json={"protocol": "openai", "base_url": "", "model": "   "}
    )
    assert resp.status_code == 422


# --- POST /test: приоритет «форма → сохранённое → env» ---


def test_connection_resolves_form_over_saved_over_env(client, fake_validator):
    client.put(
        "/api/ai-settings",
        json={"protocol": "openai", "base_url": "https://saved.test/v1",
              "model": "saved-model", "api_key": "saved-secret-token"},
    )
    resp = client.post(
        "/api/ai-settings/test",
        json={"protocol": "openai", "base_url": "", "model": "form-model", "api_key": ""},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "message": "Модель fake ответила"}

    conn = fake_validator.last
    assert conn.model == "form-model"  # из формы
    assert conn.base_url == "https://saved.test/v1"  # форма пуста → сохранённое
    assert conn.api_key == "saved-secret-token"

    # введённый в форме токен важнее сохранённого
    client.post(
        "/api/ai-settings/test",
        json={"protocol": "openai", "base_url": "", "model": "", "api_key": "form-secret-token"},
    )
    assert fake_validator.last.api_key == "form-secret-token"


def test_connection_falls_back_to_env(client, fake_validator):
    client.post(
        "/api/ai-settings/test",
        json={"protocol": "anthropic", "base_url": "", "model": "", "api_key": ""},
    )
    conn = fake_validator.last
    assert conn.model == "glm-4.5"  # env из conftest
    assert conn.base_url == "https://api.z.ai/api/anthropic"
    assert conn.api_key == "test-ai-key"


def test_connection_error_is_ok_false(client, fake_validator):
    fake_validator.error = AIValidationError("Неверный API-ключ ИИ (401)")
    body = client.post(
        "/api/ai-settings/test",
        json={"protocol": "anthropic", "base_url": "", "model": "", "api_key": "bad"},
    ).json()
    assert body == {"ok": False, "message": "Неверный API-ключ ИИ (401)"}


# --- маска токена ---


def test_mask_api_key_cases():
    assert mask_api_key("") == ""
    assert mask_api_key("short") == "••••"
    assert mask_api_key("12345678") == "••••"
    assert mask_api_key("123456789") == "123…789"
    assert mask_api_key("sk-super-secret-token") == "sk-…ken"
