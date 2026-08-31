"""Тесты нескольких шаблонов: карточки, создание, пометка «по умолчанию»,
архив, выбор в диалоге проверки (validation-config)."""

from __future__ import annotations


def save_payload(**overrides) -> dict:
    payload = {
        "name": "Шаблон интеграционных доработок",
        "description": "Для доработок интеграций",
        "title_marker": "ИНТ",
        "sections": [
            {"level": 1, "text": "Введение", "required": True, "aliases": []},
            {"level": 1, "text": "Функциональные требования", "required": True, "aliases": []},
        ],
    }
    payload.update(overrides)
    return payload


def create_template(client, **overrides) -> dict:
    resp = client.post("/api/templates", json=save_payload(**overrides))
    assert resp.status_code == 201, resp.text
    return resp.json()


def config_templates(client) -> list[dict]:
    return client.get("/api/validation-config").json()["templates"]


def test_first_template_seeded_as_default(client):
    cards = client.get("/api/templates").json()
    assert len(cards) == 1
    assert cards[0]["is_default"] is True
    assert cards[0]["is_archived"] is False
    assert cards[0]["section_count"] > 0  # сид-структура на месте
    assert cards[0]["title_marker"] == "СТ"


def test_create_template_appears_in_dialog_and_not_default(client):
    seeded_name = client.get("/api/templates").json()[0]["name"]
    card = create_template(client)
    assert card["is_default"] is False
    assert card["active_version_id"] is not None

    cards = client.get("/api/templates").json()
    assert [c["name"] for c in cards] == [seeded_name, "Шаблон интеграционных доработок"]

    # диалог проверки: дефолт — первым, новинка рядом со своим id версии
    templates = config_templates(client)
    assert templates[0]["is_default"] is True
    assert templates[1]["id"] == card["active_version_id"]
    assert templates[1]["name"] == "Шаблон интеграционных доработок"


def test_create_rejects_duplicate_name_case_insensitive(client):
    create_template(client)
    resp = client.post("/api/templates", json=save_payload(name="  шаблон интеграционных доработок "))
    assert resp.status_code == 422
    assert "уже есть" in resp.json()["detail"]


def test_put_creates_version_and_renames(client):
    card = create_template(client)
    resp = client.put(
        f"/api/templates/{card['id']}",
        json=save_payload(name="Шаблон доработок", title_marker="ДОР"),
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Шаблон доработок"

    versions = client.get(f"/api/templates/{card['id']}/versions").json()
    assert [v["id"] for v in versions] == [resp.json()["id"], card["active_version_id"]]
    assert versions[0]["is_active"] is True and versions[1]["is_active"] is False

    # активные версии соседних шаблонов не тронуты
    first = client.get("/api/templates").json()[0]
    assert first["active_version_id"] == 1  # сид-версия осталась активной


def test_put_rejects_duplicate_sibling_sections_and_foreign_name(client):
    card = create_template(client)
    resp = client.put(
        f"/api/templates/{card['id']}",
        json=save_payload(
            sections=[
                {"level": 1, "text": "Риски", "required": False, "aliases": []},
                {"level": 1, "text": "риски", "required": False, "aliases": []},
            ]
        ),
    )
    assert resp.status_code == 422 and "повторяется" in resp.json()["detail"]

    # имя занято сид-шаблоном
    seeded_name = client.get("/api/templates").json()[0]["name"]
    resp = client.put(f"/api/templates/{card['id']}", json=save_payload(name=seeded_name))
    assert resp.status_code == 422 and "уже есть" in resp.json()["detail"]


def test_switch_default_changes_dialog_preselect(client):
    card = create_template(client)
    resp = client.post(f"/api/templates/{card['id']}/default")
    assert resp.status_code == 200 and resp.json()["is_default"] is True

    templates = config_templates(client)
    assert templates[0]["name"] == "Шаблон интеграционных доработок"
    assert [t["is_default"] for t in templates] == [True, False]

    # legacy-роут теперь отдаёт активную версию нового дефолта
    assert client.get("/api/template").json()["name"] == "Шаблон интеграционных доработок"


def test_archive_hides_from_dialog_and_transfers_default(client):
    cards = client.get("/api/templates").json()
    first_id = cards[0]["id"]
    card = create_template(client)

    resp = client.post(f"/api/templates/{first_id}/archive")
    assert resp.status_code == 200 and resp.json()["is_archived"] is True

    # из диалога исчез, дефолт переехал на оставшийся
    templates = config_templates(client)
    assert [t["name"] for t in templates] == ["Шаблон интеграционных доработок"]
    assert templates[0]["is_default"] is True

    # карточка жива в списке, в архивном блоке
    cards = client.get("/api/templates").json()
    archived = [c for c in cards if c["is_archived"]]
    assert len(archived) == 1 and archived[0]["id"] == first_id

    # редактирование архива запрещено
    put = client.put(f"/api/templates/{first_id}", json=save_payload(name="Переименование"))
    assert put.status_code == 409


def test_archive_last_template_leaves_dialog_empty(client):
    cards = client.get("/api/templates").json()
    resp = client.post(f"/api/templates/{cards[0]['id']}/archive")
    assert resp.status_code == 200
    assert config_templates(client) == []
    assert client.get("/api/template").status_code == 404


def test_restore_returns_to_dialog_and_takes_default_back(client):
    cards = client.get("/api/templates").json()
    seeded_name = cards[0]["name"]
    first_id = cards[0]["id"]
    client.post(f"/api/templates/{first_id}/archive")

    resp = client.post(f"/api/templates/{first_id}/restore")
    assert resp.status_code == 200 and resp.json()["is_archived"] is False
    # дефолта ни у кого не было — возвращённый забирает пометку
    assert resp.json()["is_default"] is True
    templates = config_templates(client)
    assert templates[0]["name"] == seeded_name


def test_get_missing_template_404(client):
    assert client.get("/api/templates/999").status_code == 404
    assert client.get("/api/templates/999/versions").status_code == 404
    assert client.post("/api/templates/999/default").status_code == 404


def test_create_first_template_becomes_default_when_none(client):
    client.post("/api/templates/1/archive")  # сид уходит в архив, дефолта нет
    card = create_template(client)
    assert card["is_default"] is True
