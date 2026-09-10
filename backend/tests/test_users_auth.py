"""Тесты пользователей и ролей: вход по токену Confluence, заявки на
модерацию, права ролей, управление ролями (God)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.clients.confluence import ConfluenceClient
from app.config import Settings
from app.database import Base, engine
from app.main import create_app

USERNAME = "boss"
PASSWORD = "s3cret-пароль"
MARIA_TOKEN = "pat-maria-1234567890"


@pytest.fixture()
def auth_client():
    settings = Settings(
        auth_enabled=True,
        app_username=USERNAME,
        app_password=PASSWORD,
        confluence_base_url="https://conf.test",
        confluence_token="service-token",
        _env_file=None,
    )
    Base.metadata.drop_all(bind=engine)  # изоляция от предыдущих тестов
    with TestClient(create_app(settings)) as client:
        yield client
    Base.metadata.drop_all(bind=engine)
    from app.usecase import tasks as _tasks

    _tasks._validation_state.clear()
    _tasks._bulk_state.update(
        {"running": False, "analyst_id": None, "total": 0, "done": 0,
         "started_at": None, "finished_at": None, "error": None}
    )
    _tasks._sync_state.update({"running": False, "error": None})



@pytest.fixture()
def god_headers(auth_client):
    resp = auth_client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def _patch_whoami(monkeypatch, answer: dict, *, accept_token: str):
    """Клиент с персональным токеном несёт его в Authorization — мок принимает
    только указанный токен (чужой = 401 от Confluence)."""

    async def whoami_with_token(self) -> dict:
        auth_header = self._client.headers.get("Authorization", "")
        if auth_header == f"Bearer {accept_token}":
            return answer
        from app.clients.confluence import ConfluenceError

        raise ConfluenceError("401 Unauthorized", status_code=401)

    monkeypatch.setattr(ConfluenceClient, "whoami", whoami_with_token)


# ── вход по токену: полный цикл ──────────────────────────────────────


def test_unknown_token_creates_pending_request(auth_client, monkeypatch):
    _patch_whoami(
        monkeypatch,
        {"username": "m.smirnova", "fullName": "Мария Смирнова", "email": "maria@company.ru"},
        accept_token=MARIA_TOKEN,
    )
    resp = auth_client.post("/api/auth/token-login", json={"token": MARIA_TOKEN})
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "pending"
    assert body["full_name"] == "Мария Смирнова"
    assert body["confluence_login"] == "m.smirnova"


def test_bad_token_returns_502(auth_client, monkeypatch):
    _patch_whoami(monkeypatch, {}, accept_token=MARIA_TOKEN)
    resp = auth_client.post("/api/auth/token-login", json={"token": "pat-wrong-token-000"})
    assert resp.status_code == 502
    assert "Confluence" in resp.json()["detail"]


def test_pending_token_login_repeats_status(auth_client, monkeypatch):
    _patch_whoami(
        monkeypatch,
        {"username": "m.smirnova", "fullName": "Мария Смирнова", "email": "maria@company.ru"},
        accept_token=MARIA_TOKEN,
    )
    assert (
        auth_client.post("/api/auth/token-login", json={"token": MARIA_TOKEN}).status_code
        == 202
    )
    # повторный вход тем же токеном — тот же статус, дубли заявки нет
    again = auth_client.post("/api/auth/token-login", json={"token": MARIA_TOKEN})
    assert again.status_code == 202
    requests_list = auth_client.get("/api/auth/requests", headers=_god(auth_client)).json()
    assert len([r for r in requests_list if r["status"] == "pending"]) == 1


def _god(client) -> dict:
    resp = client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def test_approve_creates_user_and_token_then_logs_in(auth_client, monkeypatch):
    _patch_whoami(
        monkeypatch,
        {"username": "m.smirnova", "fullName": "Мария Смирнова", "email": "maria@company.ru"},
        accept_token=MARIA_TOKEN,
    )
    auth_client.post("/api/auth/token-login", json={"token": MARIA_TOKEN})

    god = _god(auth_client)
    roles = {r["name"]: r["id"] for r in auth_client.get("/api/roles", headers=god).json()}
    requests_list = auth_client.get("/api/auth/requests", headers=god).json()
    pending = next(r for r in requests_list if r["status"] == "pending")

    approved = auth_client.post(
        f"/api/auth/requests/{pending['id']}/approve",
        json={"role_id": roles["Lead"]},
        headers=god,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    # одобренный входит тем же токеном
    session = auth_client.post("/api/auth/token-login", json={"token": MARIA_TOKEN})
    assert session.status_code == 200
    me = session.json()["user"]
    assert me["full_name"] == "Мария Смирнова"
    assert me["role_name"] == "Lead"
    assert me["is_god"] is False


def test_reject_then_reapply_then_approve(auth_client, monkeypatch):
    skv_token = "pat-skvortsov-9876543210"
    _patch_whoami(
        monkeypatch,
        {"username": "p.skvortsov", "fullName": "Пётр Скворцов", "email": "p@company.ru"},
        accept_token=skv_token,
    )
    auth_client.post("/api/auth/token-login", json={"token": skv_token})
    god = _god(auth_client)
    roles = {r["name"]: r["id"] for r in auth_client.get("/api/roles", headers=god).json()}
    pending = next(
        r
        for r in auth_client.get("/api/auth/requests", headers=god).json()
        if r["status"] == "pending"
    )

    rejected = auth_client.post(
        f"/api/auth/requests/{pending['id']}/reject", headers=god
    )
    assert rejected.status_code == 200

    # вход по отклонённому токену — 403 с подсказкой о повторной подаче
    denied = auth_client.post("/api/auth/token-login", json={"token": skv_token})
    assert denied.status_code == 403

    # повторная подача тем же токеном — снова pending
    reapplied = auth_client.post("/api/auth/reapply", json={"token": skv_token})
    assert reapplied.status_code == 202
    assert reapplied.json()["status"] == "pending"

    # God может вернуть заявку в новые и со своей стороны
    reopened = auth_client.post(
        f"/api/auth/requests/{pending['id']}/reopen", headers=god
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "pending"


# ── права ролей ──────────────────────────────────────────────────────


def _approved_lead_session(auth_client, monkeypatch) -> dict:
    """Флоу: токен → заявка → одобрение роли Lead → сессия лида."""
    _patch_whoami(
        monkeypatch,
        {"username": "m.smirnova", "fullName": "Мария Смирнова", "email": "maria@company.ru"},
        accept_token=MARIA_TOKEN,
    )
    auth_client.post("/api/auth/token-login", json={"token": MARIA_TOKEN})
    god = _god(auth_client)
    roles = {r["name"]: r["id"] for r in auth_client.get("/api/roles", headers=god).json()}
    pending = next(
        r
        for r in auth_client.get("/api/auth/requests", headers=god).json()
        if r["status"] == "pending"
    )
    auth_client.post(
        f"/api/auth/requests/{pending['id']}/approve",
        json={"role_id": roles["Lead"]},
        headers=god,
    )
    session = auth_client.post("/api/auth/token-login", json={"token": MARIA_TOKEN})
    return {"Authorization": f"Bearer {session.json()['token']}"}


def test_lead_cannot_delete_cluster_but_can_create(auth_client, monkeypatch):
    lead = _approved_lead_session(auth_client, monkeypatch)
    created = auth_client.post(
        "/api/clusters",
        json={"name": "Медиа", "description": None, "color": None},
        headers=lead,
    )
    assert created.status_code == 201
    cluster_id = created.json()["id"]
    denied = auth_client.delete(f"/api/clusters/{cluster_id}", headers=lead)
    assert denied.status_code == 403
    assert "Недостаточно прав" in denied.json()["detail"]


def test_lead_cannot_moderate_or_manage_roles(auth_client, monkeypatch):
    lead = _approved_lead_session(auth_client, monkeypatch)
    assert auth_client.get("/api/auth/requests", headers=lead).status_code == 403
    resp = auth_client.post(
        "/api/roles",
        json={"name": "Хакер", "permissions": []},
        headers=lead,
    )
    assert resp.status_code == 403
    # просмотр ролей и каталога прав — доступен (read-only экран)
    assert auth_client.get("/api/roles", headers=lead).status_code == 200
    assert auth_client.get("/api/roles/permissions", headers=lead).status_code == 200


def test_lead_can_assign_lead_to_analyst(auth_client, monkeypatch):
    lead = _approved_lead_session(auth_client, monkeypatch)
    analyst = auth_client.post(
        "/api/analysts",
        json={"full_name": "Алиев Рустам", "email": "aliev@company.ru"},
        headers=lead,
    )
    assert analyst.status_code == 201
    leads = auth_client.get("/api/users?role=Lead", headers=lead).json()
    assert len(leads) == 1
    maria = leads[0]
    assert maria["role_name"] == "Lead"
    assigned = auth_client.put(
        f"/api/analysts/{analyst.json()['id']}/lead",
        json={"user_id": maria["id"]},
        headers=lead,
    )
    assert assigned.status_code == 200
    card = auth_client.get(f"/api/analysts/{analyst.json()['id']}", headers=lead).json()
    assert card["lead_user_id"] == maria["id"]
    assert card["lead_name"] == "Мария Смирнова"



# ── управление ролями (God) ──────────────────────────────────────────


def test_role_crud_and_guards(auth_client, monkeypatch):
    god = _god(auth_client)
    roles = {r["name"]: r["id"] for r in auth_client.get("/api/roles", headers=god).json()}

    # God-роль системная: править и удалять нельзя
    assert (
        auth_client.put(
            f"/api/roles/{roles['God']}", json={"name": "X", "permissions": []}, headers=god
        ).status_code
        == 409
    )
    assert auth_client.delete(f"/api/roles/{roles['God']}", headers=god).status_code == 409

    # создание своей роли; неизвестное право — 422; дубль — 409
    created = auth_client.post(
        "/api/roles",
        json={"name": "Наблюдатель", "permissions": ["checks", "comments"]},
        headers=god,
    )
    assert created.status_code == 201
    viewer_id = created.json()["id"]
    assert created.json()["is_system"] is False

    assert (
        auth_client.post(
            "/api/roles", json={"name": "Наблюдатель", "permissions": []}, headers=god
        ).status_code
        == 409
    )
    assert (
        auth_client.post(
            "/api/roles", json={"name": "X", "permissions": ["nope"]}, headers=god
        ).status_code
        == 422
    )

    # правка своей роли
    updated = auth_client.put(
        f"/api/roles/{viewer_id}",
        json={"name": "Наблюдатель-2", "permissions": ["checks"]},
        headers=god,
    )
    assert updated.status_code == 200
    assert updated.json()["permissions"] == ["checks"]

    # удаление занятой роли запрещено: назначаем её пользователю через заявку
    from tests.test_users_auth import _patch_whoami  # noqa: F401 — уже в модуле

    async def _whoami_ok(self) -> dict:
        return {"username": "m.smirnova", "fullName": "Мария Смирнова", "email": "m@company.ru"}

    import contextlib

    monkeypatch.setattr(ConfluenceClient, "whoami", _whoami_ok)
    auth_client.post("/api/auth/token-login", json={"token": "pat-role-assign-000"})
    req = next(
        r
        for r in auth_client.get("/api/auth/requests", headers=god).json()
        if r["status"] == "pending"
    )
    auth_client.post(
        f"/api/auth/requests/{req['id']}/approve",
        json={"role_id": viewer_id},
        headers=god,
    )
    assert auth_client.delete(f"/api/roles/{viewer_id}", headers=god).status_code == 409

    # смена роли пользователя освобождает роль — теперь удаляется
    user_id = next(
        u["id"] for u in auth_client.get(f"/api/users?role_id={viewer_id}", headers=god).json()
    )
    assert (
        auth_client.put(
            f"/api/auth/users/{user_id}/role", json={"role_id": roles["Lead"]}, headers=god
        ).status_code
        == 200
    )
    assert auth_client.delete(f"/api/roles/{viewer_id}", headers=god).status_code == 204


def test_reminders_are_personal(auth_client, monkeypatch):
    """Напоминание лида не видно God-у в списке, а прямая операция — 404:
    напоминалки строго личные."""
    lead = _approved_lead_session(auth_client, monkeypatch)
    god = _god(auth_client)

    # лид создаёт напоминание по аналитику
    analyst = auth_client.post(
        "/api/analysts",
        json={"full_name": "Аналитик для напоминания", "email": "rem-user@company.ru"},
        headers=lead,
    ).json()
    created = auth_client.post(
        "/api/reminders",
        json={"analyst_id": analyst["id"], "text": "лидское напоминание", "remind_at": None},
        headers=lead,
    ).json()

    # God в списке видит только свои (пусто), лид — своё
    assert [r["id"] for r in auth_client.get("/api/reminders", headers=god).json()] == []
    mine = auth_client.get("/api/reminders", headers=lead).json()
    assert [r["id"] for r in mine] == [created["id"]]

    # прямая операция God-а над чужим — 404 (не раскрываем существование)
    assert auth_client.post(f"/api/reminders/{created['id']}/done", headers=god).status_code == 404
    assert auth_client.delete(f"/api/reminders/{created['id']}", headers=god).status_code == 404
