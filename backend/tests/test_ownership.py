"""Тесты персонализации: владельцы шаблонов/критериев, общий реестр с
копированием, guard личного доступа к ИИ, «Мои аналитики» у лида."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.clients.confluence import ConfluenceClient
from app.config import Settings
from app.database import Base, SessionLocal, engine
from app.main import create_app
from app.models import Analyst, ConfluenceDocument
from app.utils import now_utc

USERNAME = "boss"
PASSWORD = "s3cret-пароль"
LEAD_TOKEN = "pat-ownership-lead-0001"


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
    Base.metadata.drop_all(bind=engine)
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



def _patch_whoami(monkeypatch, answer: dict, *, accept_token: str):
    async def whoami_with_token(self) -> dict:
        if self._client.headers.get("Authorization", "") == f"Bearer {accept_token}":
            return answer
        from app.clients.confluence import ConfluenceError

        raise ConfluenceError("401 Unauthorized", status_code=401)

    monkeypatch.setattr(ConfluenceClient, "whoami", whoami_with_token)


def _god(client) -> dict:
    resp = client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def _lead_session(client, monkeypatch) -> dict:
    """Флоу до рабочей сессии лида (роль Lead по умолчанию при одобрении)."""
    _patch_whoami(
        monkeypatch,
        answer={
            "username": "m.smirnova",
            "fullName": "Мария Смирнова",
            "email": "maria@company.ru",
        },
        accept_token=LEAD_TOKEN,
    )
    client.post("/api/auth/token-login", json={"token": LEAD_TOKEN})
    god = _god(client)
    roles = {r["name"]: r["id"] for r in client.get("/api/roles", headers=god).json()}
    pending = next(
        r
        for r in client.get("/api/auth/requests", headers=god).json()
        if r["status"] == "pending"
    )
    client.post(
        f"/api/auth/requests/{pending['id']}/approve",
        json={"role_id": roles["Lead"]},
        headers=god,
    )
    session = client.post("/api/auth/token-login", json={"token": LEAD_TOKEN})
    return {"Authorization": f"Bearer {session.json()['token']}"}


# ── шаблоны ──────────────────────────────────────────────────────────


def test_god_sees_seeded_template_lead_starts_empty(auth_client, monkeypatch):
    lead = _lead_session(auth_client, monkeypatch)
    god = _god(auth_client)

    god_cards = auth_client.get("/api/templates", headers=god).json()
    assert len(god_cards) == 1  # сид из requirements_template.json — владелец God
    lead_cards = auth_client.get("/api/templates", headers=lead).json()
    assert lead_cards == []


def test_lead_cannot_touch_god_template(auth_client, monkeypatch):
    lead = _lead_session(auth_client, monkeypatch)
    god_template_id = auth_client.get("/api/templates", headers=_god(auth_client)).json()[0][
        "id"
    ]

    assert auth_client.get(f"/api/templates/{god_template_id}", headers=lead).status_code == 404
    assert (
        auth_client.put(
            f"/api/templates/{god_template_id}",
            json={"name": "Взлом", "description": None, "title_marker": "X", "sections": []},
            headers=lead,
        ).status_code
        == 404
    )


def test_registry_lists_others_and_copy_belongs_to_lead(auth_client, monkeypatch):
    lead = _lead_session(auth_client, monkeypatch)
    god = _god(auth_client)
    god_template_id = auth_client.get("/api/templates", headers=god).json()[0]["id"]

    registry = auth_client.get("/api/templates/registry", headers=lead).json()
    assert [r["id"] for r in registry] == [god_template_id]
    assert registry[0]["owner_name"] == "Администратор сервиса"

    copied = auth_client.post(f"/api/templates/{god_template_id}/copy", headers=lead)
    assert copied.status_code == 201
    assert "(копия)" in copied.json()["name"]

    # копия в моих шаблонах; оригинал по-прежнему в реестре
    assert len(auth_client.get("/api/templates", headers=lead).json()) == 1
    assert (
        auth_client.get("/api/templates/registry", headers=lead).json()[0]["id"]
        == god_template_id
    )


def test_lead_creates_and_archives_own_template(auth_client, monkeypatch):
    lead = _lead_session(auth_client, monkeypatch)
    created = auth_client.post(
        "/api/templates",
        json={
            "name": "Мой шаблон",
            "description": None,
            "title_marker": "МТ",
            "sections": [{"level": 1, "text": "Введение", "required": True, "aliases": []}],
        },
        headers=lead,
    )
    assert created.status_code == 201
    template_id = created.json()["id"]
    assert created.json()["is_default"] is True  # первый мой — по умолчанию

    archived = auth_client.post(f"/api/templates/{template_id}/archive", headers=lead)
    assert archived.status_code == 200
    assert archived.json()["is_archived"] is True


# ── критерии ─────────────────────────────────────────────────────────


def test_criteria_are_personal_with_registry_copy(auth_client, monkeypatch):
    lead = _lead_session(auth_client, monkeypatch)
    god = _god(auth_client)

    god_criteria = auth_client.get("/api/ai-criteria", headers=god).json()
    assert len(god_criteria) == 3
    assert auth_client.get("/api/ai-criteria", headers=lead).json() == []

    registry = auth_client.get("/api/ai-criteria/registry", headers=lead).json()
    assert len(registry) == 3
    assert registry[0]["owner_name"] == "Администратор сервиса"

    copied = auth_client.post(f"/api/ai-criteria/{registry[0]['id']}/copy", headers=lead)
    assert copied.status_code == 201
    mine = auth_client.get("/api/ai-criteria", headers=lead).json()
    assert len(mine) == 1
    assert "(копия)" in mine[0]["name"]


# ── guard личного доступа к ИИ ───────────────────────────────────────


def test_lead_without_ai_setup_blocked_from_ai_check(auth_client, monkeypatch):
    """Без личного доступа к ИИ лид не запускает ИИ-проверку (409);
    шаблонная проверка — доступна."""
    lead = _lead_session(auth_client, monkeypatch)
    analyst = auth_client.post(
        "/api/analysts",
        json={"full_name": "Алиев Рустам", "email": "aliev@company.ru"},
        headers=lead,
    ).json()
    with SessionLocal() as db:
        db.add(
            ConfluenceDocument(
                analyst_id=analyst["id"],
                confluence_page_id=str(now_utc().timestamp()).replace(".", ""),
                title="Документ лида",
                url="https://conf.test/x",
                content_html="<h1>Введение</h1>",
                last_modified_in_confluence_at=now_utc(),
            )
        )
        db.commit()

    resp = auth_client.post(
        "/api/documents/validate-batch",
        json={"document_ids": [1], "checks": ["ai"]},
        headers=lead,
    )
    assert resp.status_code == 409
    assert "Мой доступ к ИИ" in resp.json()["detail"]

    # шаблонная проверка не требует ИИ
    ok = auth_client.post(
        "/api/documents/validate-batch",
        json={"document_ids": [1], "checks": ["template"]},
        headers=lead,
    )
    assert ok.status_code == 202


# ── мои аналитики у лида ─────────────────────────────────────────────


def test_my_analysts_panel_for_lead(auth_client, monkeypatch):
    lead = _lead_session(auth_client, monkeypatch)
    analyst = auth_client.post(
        "/api/analysts",
        json={"full_name": "Алиев Рустам", "email": "aliev@company.ru"},
        headers=lead,
    ).json()
    leads = auth_client.get("/api/users?role=Lead", headers=lead).json()
    maria = next(u for u in leads if u["full_name"] == "Мария Смирнова")
    assert (
        auth_client.put(
            f"/api/analysts/{analyst['id']}/lead",
            json={"user_id": maria["id"]},
            headers=lead,
        ).status_code
        == 200
    )

    body = auth_client.get("/api/dashboard", headers=lead).json()
    assert len(body["my_analysts"]) == 1
    assert body["my_analysts"][0]["name"] == "Алиев Рустам"

    # карточка аналитика знает своего лида
    card = auth_client.get(f"/api/analysts/{analyst['id']}", headers=lead).json()
    assert card["lead_user_id"] == maria["id"]
    assert card["lead_name"] == "Мария Смирнова"

    # у God своих подопечных нет
    god_body = auth_client.get("/api/dashboard", headers=_god(auth_client)).json()
    assert god_body["my_analysts"] == []
