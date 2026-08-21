"""Тесты реестра аналитиков (ФТ-CR-1, ФТ-CR-2)."""


def _create(client, **overrides):
    payload = {"full_name": "Алиев Рустам", "email": "raaliev@mts.ru"}
    payload.update(overrides)
    return client.post("/api/analysts", json=payload)


def test_create_analyst(client):
    resp = _create(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["full_name"] == "Алиев Рустам"
    assert body["email"] == "raaliev@mts.ru"
    assert body["documents_count"] == 0
    assert body["id"] > 0


def test_create_analyst_duplicate_email(client):
    assert _create(client).status_code == 201
    resp = _create(client, full_name="Другое имя")
    assert resp.status_code == 409


def test_create_analyst_invalid_payload(client):
    assert client.post("/api/analysts", json={"full_name": "", "email": "x"}).status_code == 422
    assert (
        client.post("/api/analysts", json={"full_name": "Имя", "email": "не-email"}).status_code
        == 422
    )


def test_list_analysts(client):
    _create(client)
    _create(client, full_name="Грудинин Александр", email="aigrudini2@mts.ru")
    resp = client.get("/api/analysts")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    # сортировка по ФИО
    assert items[0]["full_name"] == "Алиев Рустам"
    assert items[1]["full_name"] == "Грудинин Александр"


def test_get_analyst_not_found(client):
    assert client.get("/api/analysts/999").status_code == 404


def test_get_analyst_with_username_override(client):
    resp = _create(client, confluence_username="raaliev")
    assert resp.status_code == 201
    body = client.get(f"/api/analysts/{resp.json()['id']}").json()
    assert body["confluence_username"] == "raaliev"
