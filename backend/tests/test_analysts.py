"""Тесты реестра аналитиков (ФТ-CR-1, ФТ-CR-2)."""

from sqlalchemy import select


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


# --- редактирование ---


def test_update_analyst(client):
    created = _create(client).json()
    resp = client.put(
        f"/api/analysts/{created['id']}",
        json={
            "full_name": "Алиев Рустам Редактированович",
            "email": "New.Email@MTS.ru",
            "confluence_username": "raaliev",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["full_name"] == "Алиев Рустам Редактированович"
    assert body["email"] == "new.email@mts.ru"  # приводится к нижнему регистру
    assert body["confluence_username"] == "raaliev"
    # перечитали — изменения сохранились
    assert client.get(f"/api/analysts/{created['id']}").json()["full_name"].endswith(
        "Редактированович"
    )


def test_update_analyst_keeps_own_email(client):
    created = _create(client).json()
    resp = client.put(
        f"/api/analysts/{created['id']}",
        json={"full_name": "То же имя", "email": created["email"]},
    )
    # свой собственный email — не дубль
    assert resp.status_code == 200


def test_update_analyst_duplicate_email(client):
    first = _create(client).json()
    second = _create(client, full_name="Второй", email="second@mts.ru").json()
    resp = client.put(
        f"/api/analysts/{second['id']}",
        json={"full_name": "Второй", "email": first["email"]},
    )
    assert resp.status_code == 409
    # карточка не изменилась
    assert client.get(f"/api/analysts/{second['id']}").json()["email"] == "second@mts.ru"


def test_update_analyst_not_found_and_invalid(client):
    assert (
        client.put("/api/analysts/999", json={"full_name": "X", "email": "x@mts.ru"}).status_code
        == 404
    )
    created = _create(client).json()
    assert (
        client.put(
            f"/api/analysts/{created['id']}", json={"full_name": "X", "email": "не-email"}
        ).status_code
        == 422
    )


# --- удаление ---


def test_delete_analyst_cascades_documents(client):
    from app.database import SessionLocal
    from app.models import Analyst, ConfluenceDocument, ValidationReport

    created = _create(client, full_name="На удаление", email="del@mts.ru").json()
    other = _create(client, full_name="Остаётся", email="keep@mts.ru").json()
    with SessionLocal() as db:
        doomed = ConfluenceDocument(
            analyst_id=created["id"],
            confluence_page_id="del-1",
            title="[СТ] Удаляемый",
            url="https://conf.test/del-1",
            content_html="<h1>x</h1>",
        )
        survivor = ConfluenceDocument(
            analyst_id=other["id"],
            confluence_page_id="keep-1",
            title="[СТ] Остающийся",
            url="https://conf.test/keep-1",
            content_html="<h1>x</h1>",
        )
        db.add_all([doomed, survivor])
        db.flush()
        db.add(ValidationReport(document_id=doomed.id, triggered_by="auto"))
        db.commit()

    assert client.delete(f"/api/analysts/{created['id']}").status_code == 204
    # повторное удаление и GET — 404
    assert client.delete(f"/api/analysts/{created['id']}").status_code == 404
    assert client.get(f"/api/analysts/{created['id']}").status_code == 404

    with SessionLocal() as db:
        assert db.get(Analyst, created["id"]) is None
        docs = db.scalars(
            select(ConfluenceDocument).where(ConfluenceDocument.analyst_id == created["id"])
        ).all()
        assert docs == []
        reports = db.scalars(select(ValidationReport)).all()
        assert reports == []  # отчёт удаляемого документа ушёл каскадом
        kept = db.scalars(
            select(ConfluenceDocument).where(ConfluenceDocument.analyst_id == other["id"])
        ).all()
        assert len(kept) == 1  # чужие документы не тронуты


def test_delete_analyst_not_found(client):
    assert client.delete("/api/analysts/999").status_code == 404
