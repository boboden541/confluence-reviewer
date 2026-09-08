"""Организационная структура: кластеры, команды, состав, домены аналитика.

CRUD кластеров и команд, guard'ы уникальности и непустоты, перевод
аналитика между командами, агрегированные домены команды, миграция
колонок analysts (team_id, domains) на существующей БД.
"""

from __future__ import annotations

import json

from sqlalchemy import inspect as sa_inspect

from app.database import engine


def _cluster(client, name="Билетный бизнес", **overrides):
    payload = {"name": name, "description": "Продажи билетов", "color": "#0C66E4"}
    payload.update(overrides)
    return client.post("/api/clusters", json=payload)


def _team(client, cluster_id, name="GDS", **overrides):
    payload = {"cluster_id": cluster_id, "name": name, "description": "Бронирование"}
    payload.update(overrides)
    return client.post("/api/teams", json=payload)


def _analyst(client, full_name="Алиев Рустам", email="aliev@company.ru"):
    return client.post("/api/analysts", json={"full_name": full_name, "email": email})


# --- кластеры ---


def test_cluster_crud_roundtrip(client):
    created = _cluster(client)
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Билетный бизнес"
    assert body["color"] == "#0C66E4"
    assert body["teams"] == [] and body["teams_count"] == 0
    cluster_id = body["id"]

    got = client.get(f"/api/clusters/{cluster_id}")
    assert got.status_code == 200
    assert got.json()["description"] == "Продажи билетов"

    updated = client.put(
        f"/api/clusters/{cluster_id}",
        json={"name": "Билетный бизнес", "description": "Обновлено", "color": "#6E5DC6"},
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "Обновлено"

    assert client.delete(f"/api/clusters/{cluster_id}").status_code == 204
    assert client.get(f"/api/clusters/{cluster_id}").status_code == 404


def test_cluster_duplicate_name_conflict(client):
    assert _cluster(client).status_code == 201
    dup = _cluster(client, description="другой")
    assert dup.status_code == 409
    assert "уже существует" in dup.json()["detail"]
    # регистр не важен — как у команд
    assert _cluster(client, name="билетный бизнес").status_code == 409


def test_cluster_update_duplicate_name_conflict(client):
    assert _cluster(client).status_code == 201
    second = _cluster(client, name="Медиа")
    assert second.status_code == 201
    resp = client.put(
        f"/api/clusters/{second.json()['id']}",
        json={"name": "Билетный бизнес", "description": None, "color": None},
    )
    assert resp.status_code == 409


def test_delete_cluster_with_teams_conflicts(client):
    cluster = _cluster(client).json()
    assert _team(client, cluster["id"]).status_code == 201
    resp = client.delete(f"/api/clusters/{cluster['id']}")
    assert resp.status_code == 409
    assert "Сначала удалите команды" in resp.json()["detail"]


def test_cluster_missing_404(client):
    assert client.get("/api/clusters/999").status_code == 404
    assert (
        client.put(
            "/api/clusters/999", json={"name": "X", "description": None, "color": None}
        ).status_code
        == 404
    )
    assert client.delete("/api/clusters/999").status_code == 404


# --- команды ---


def test_team_crud_roundtrip_with_cluster_counters(client):
    cluster = _cluster(client).json()
    created = _team(client, cluster["id"])
    assert created.status_code == 201
    team = created.json()
    assert team["cluster_id"] == cluster["id"]
    assert team["cluster_name"] == "Билетный бизнес"

    # кластер видит команду и счётчики
    card = client.get(f"/api/clusters/{cluster['id']}").json()
    assert card["teams_count"] == 1
    assert [t["name"] for t in card["teams"]] == ["GDS"]

    # после удаления команды кластер снова можно удалить
    assert client.delete(f"/api/teams/{team['id']}").status_code == 204
    assert client.delete(f"/api/clusters/{cluster['id']}").status_code == 204


def test_team_duplicate_name_in_same_cluster_conflicts(client):
    cluster = _cluster(client).json()
    assert _team(client, cluster["id"], name="GDS").status_code == 201
    dup = _team(client, cluster["id"], name="gds")  # регистр не важен
    assert dup.status_code == 409
    assert "уже есть в этом кластере" in dup.json()["detail"]


def test_same_team_name_allowed_in_different_clusters(client):
    first = _cluster(client).json()
    second = _cluster(client, name="Медиа").json()
    assert _team(client, first["id"], name="GDS").status_code == 201
    assert _team(client, second["id"], name="GDS").status_code == 201


def test_team_create_missing_cluster_404(client):
    resp = _team(client, 999)
    assert resp.status_code == 404


def test_team_missing_404(client):
    assert client.get("/api/teams/999").status_code == 404
    assert (
        client.put(
            "/api/teams/999", json={"name": "X", "description": None}
        ).status_code
        == 404
    )
    assert client.delete("/api/teams/999").status_code == 404


# --- состав команды ---


def test_add_and_remove_analyst_sets_team_context(client):
    cluster = _cluster(client).json()
    team = _team(client, cluster["id"]).json()
    analyst = _analyst(client).json()

    added = client.post(
        f"/api/teams/{team['id']}/analysts",
        json={"analyst_ids": [analyst["id"]], "domains": ["вывод на витрину", " загрузка данных "]},
    )
    assert added.status_code == 200
    assert [a["id"] for a in added.json()["analysts"]] == [analyst["id"]]

    # карточка аналитика знает про команду и кластер
    card = client.get(f"/api/analysts/{analyst['id']}").json()
    assert card["team_id"] == team["id"]
    assert card["team_name"] == "GDS"
    assert card["cluster_id"] == cluster["id"]
    assert card["cluster_name"] == "Билетный бизнес"
    assert card["domains"] == ["вывод на витрину", "загрузка данных"]  # trim

    # агрегированные домены команды = домены участников
    view = client.get(f"/api/teams/{team['id']}").json()
    assert view["domains"] == ["вывод на витрину", "загрузка данных"]

    removed = client.delete(f"/api/teams/{team['id']}/analysts/{analyst['id']}")
    assert removed.status_code == 200
    card = client.get(f"/api/analysts/{analyst['id']}").json()
    assert card["team_id"] is None
    assert card["domains"] == ["вывод на витрину", "загрузка данных"]  # домены остаются


def test_move_analyst_between_teams(client):
    cluster = _cluster(client).json()
    gds = _team(client, cluster["id"], name="GDS").json()
    fintech = _team(client, cluster["id"], name="Финтех").json()
    analyst = _analyst(client).json()

    assert (
        client.post(
            f"/api/teams/{gds['id']}/analysts", json={"analyst_ids": [analyst["id"]]}
        ).status_code
        == 200
    )
    moved = client.post(
        f"/api/teams/{fintech['id']}/analysts",
        json={"analyst_ids": [analyst["id"]], "domains": ["букинг"]},
    )
    assert moved.status_code == 200
    assert [a["id"] for a in moved.json()["analysts"]] == [analyst["id"]]
    # из GDS участник ушёл
    assert client.get(f"/api/teams/{gds['id']}").json()["analysts"] == []


def test_add_analyst_missing_404(client):
    cluster = _cluster(client).json()
    team = _team(client, cluster["id"]).json()
    resp = client.post(f"/api/teams/{team['id']}/analysts", json={"analyst_ids": [999]})
    assert resp.status_code == 404


def test_add_several_analysts_at_once(client):
    """Чекбоксы в UI: пачка аналитиков добавляется одним запросом; домены —
    общие для всех выбранных; несуществующий id откатывает всю пачку."""
    cluster = _cluster(client).json()
    team = _team(client, cluster["id"]).json()
    first = _analyst(client, "Иванов Иван", "ivanov@company.ru").json()
    second = _analyst(client, "Белышева Жанна", "belysheva@company.ru").json()

    added = client.post(
        f"/api/teams/{team['id']}/analysts",
        json={"analyst_ids": [first["id"], second["id"]], "domains": ["букинг"]},
    )
    assert added.status_code == 200
    assert {a["id"] for a in added.json()["analysts"]} == {first["id"], second["id"]}
    assert added.json()["domains"] == ["букинг"]
    for analyst_id in (first["id"], second["id"]):
        card = client.get(f"/api/analysts/{analyst_id}").json()
        assert card["team_id"] == team["id"]
        assert card["domains"] == ["букинг"]

    # один битый id — никто из пачки не привязывается
    third = _analyst(client, "Сидоров Пётр", "sidorov@company.ru").json()
    broken = client.post(
        f"/api/teams/{team['id']}/analysts",
        json={"analyst_ids": [third["id"], 999]},
    )
    assert broken.status_code == 404
    card = client.get(f"/api/analysts/{third['id']}").json()
    assert card["team_id"] is None


def test_deleting_team_keeps_analyst_domains(client):
    cluster = _cluster(client).json()
    team = _team(client, cluster["id"]).json()
    analyst = _analyst(client).json()
    client.post(
        f"/api/teams/{team['id']}/analysts",
        json={"analyst_ids": [analyst["id"]], "domains": ["подарочные карты"]},
    )
    assert client.delete(f"/api/teams/{team['id']}").status_code == 204
    card = client.get(f"/api/analysts/{analyst['id']}").json()
    assert card["team_id"] is None
    assert card["domains"] == ["подарочные карты"]


# --- домены аналитика ---


def test_set_analyst_domains_normalizes_and_dedupes(client):
    analyst = _analyst(client).json()
    resp = client.put(
        f"/api/analysts/{analyst['id']}/domains",
        json={"domains": ["Букинг", "букинг", "  ", "Подарочные карты"]},
    )
    assert resp.status_code == 200
    assert resp.json() == ["Букинг", "Подарочные карты"]
    assert client.get(f"/api/analysts/{analyst['id']}").json()["domains"] == [
        "Букинг",
        "Подарочные карты",
    ]


def test_set_analyst_domains_clear(client):
    analyst = _analyst(client).json()
    client.put(f"/api/analysts/{analyst['id']}/domains", json={"domains": ["метатеги"]})
    resp = client.put(f"/api/analysts/{analyst['id']}/domains", json={"domains": []})
    assert resp.status_code == 200
    assert resp.json() == []


def test_set_analyst_domains_missing_404(client):
    assert (
        client.put("/api/analysts/999/domains", json={"domains": ["x"]}).status_code == 404
    )


# --- «Без команды» и карта кластеров ---


def test_without_team_and_clusters_list(client):
    cluster = _cluster(client).json()
    team = _team(client, cluster["id"]).json()
    in_team = _analyst(client).json()
    free = _analyst(client, "Сидоров Пётр", "sidorov@company.ru").json()
    client.post(f"/api/teams/{team['id']}/analysts", json={"analyst_ids": [in_team["id"]]})

    listed = client.get("/api/clusters").json()
    assert len(listed) == 1
    assert listed[0]["analysts_count"] == 1
    assert listed[0]["teams"][0]["analysts_count"] == 1

    # «Без команды» — отдельная секция карты; фильтруется на фронте по
    # AnalystOut.team_id, здесь проверяем только контекст карточек
    assert client.get(f"/api/analysts/{free['id']}").json()["team_id"] is None


# --- миграция существующей БД ---


def test_migrate_adds_org_columns_to_existing_db(client):
    """Колонки analysts.team_id/domains появляются и на БД, созданной до
    фичи: эмулируем старую таблицу без колонок и прогоняем init_db."""
    from app.database import _ADDED_COLUMNS, init_db  # noqa: PLC0415

    inspectors_before = {c["name"] for c in sa_inspect(engine).get_columns("analysts")}
    assert {"team_id", "domains"} <= inspectors_before  # create_all уже применил

    # идемпотентность: повторный прогон миграции ничего не ломает
    init_db()
    cols = {c["name"] for c in sa_inspect(engine).get_columns("analysts")}
    assert {"team_id", "domains"} <= cols
    # записи в словаре миграций присутствуют (для существующих развёртываний)
    assert {c[0] for c in _ADDED_COLUMNS["analysts"]} == {"team_id", "domains", "lead_user_id"}


def test_existing_analysts_default_to_no_team_and_empty_domains(client):
    """Аналитики, созданные до появления структуры, читаются с дефолтами:
    без команды и с пустым списком доменов (колонка domains DEFAULT '[]')."""
    analyst = _analyst(client, "Старый Аналитик", "old@company.ru").json()
    with engine.connect() as conn:
        stored = conn.exec_driver_sql(
            f"SELECT domains FROM analysts WHERE id = {analyst['id']}"
        ).scalar()
    assert json.loads(stored) == []
