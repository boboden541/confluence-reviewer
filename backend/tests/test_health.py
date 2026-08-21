"""Тесты health-check и первичного наполнения."""

from app.seed import parse_seed_line


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_parse_seed_line_valid():
    assert parse_seed_line("Иванов Иван:ivanov@mts.ru") == ("Иванов Иван", "ivanov@mts.ru")


def test_parse_seed_line_invalid():
    assert parse_seed_line("без-email") is None
    assert parse_seed_line("Имя:не-email") is None
    assert parse_seed_line(":only@mts.ru") is None
