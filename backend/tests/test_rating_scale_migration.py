"""Миграция шкалы оценок 1..5 → 1..10 (database._migrate_rating_scale).

Юниты здесь всегда sqlite (conftest принудительно), а sqlite не умеет
DROP/ADD CONSTRAINT — postgres-ветку миграции (удвоение баллов + смена
констрейнта) юнитами не проверить. Покрывается живым смоуком в docker:
снапшот оценок до/после, констрейнт по имени, идемпотентность restart'ом.

Что проверяем юнитами: create_all создаёт новую шкалу и миграция на ней
no-op; на не-postgres миграция не трогает даже таблицу старой формы.
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.database import Base, SessionLocal, engine, _migrate_rating_scale


def setup_function(_):
    Base.metadata.create_all(bind=engine)


def teardown_function():
    Base.metadata.drop_all(bind=engine)


def check_names() -> set[str]:
    inspector = inspect(engine)
    return {c["name"] for c in inspector.get_check_constraints("criterion_ratings")}


def test_create_all_uses_new_scale_constraint():
    # create_all создаёт таблицу сразу по новой шкале — имя констрейнта и есть
    # маркер «миграция уже применена»
    names = check_names()
    assert "ck_criterion_ratings_score_1_10" in names
    assert "ck_criterion_ratings_score" not in names

    # на такой таблице миграция — no-op: баллы и констрейнт не меняются
    with SessionLocal() as db:
        db.execute(
            text(
                "INSERT INTO criterion_ratings "
                "(document_id, criterion_id, score, created_at, updated_at) "
                "VALUES (1, 1, 7, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
        db.commit()

    _migrate_rating_scale()  # идемпотентность: повторный вызов не должен падать
    _migrate_rating_scale()

    with SessionLocal() as db:
        assert db.execute(text("SELECT score FROM criterion_ratings")).scalar() == 7
    assert check_names() == names


def test_sqlite_never_touches_old_shaped_table():
    """Старая форма таблицы (констрейнт 1..5 со старым именем) на sqlite
    остаётся как есть: миграция работает только с postgres."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE criterion_ratings"))
        conn.execute(
            text(
                "CREATE TABLE criterion_ratings ("
                "id INTEGER NOT NULL PRIMARY KEY, "
                "document_id INTEGER NOT NULL, "
                "criterion_id INTEGER NOT NULL, "
                "score INTEGER NOT NULL, "
                "created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL, "
                "CONSTRAINT uq_criterion_ratings_pair UNIQUE (document_id, criterion_id), "
                "CONSTRAINT ck_criterion_ratings_score CHECK (score BETWEEN 1 AND 5))"
            )
        )
        conn.execute(
            text(
                "INSERT INTO criterion_ratings "
                "(document_id, criterion_id, score, created_at, updated_at) "
                "VALUES (1, 1, 3, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )

    _migrate_rating_scale()  # молча: не postgres — ничего не делать

    with SessionLocal() as db:
        assert db.execute(text("SELECT score FROM criterion_ratings")).scalar() == 3
    # sqlite рефлексит констрейнты обрывком DDL («CONSTRAINT <имя>»), а не голым
    # именем как postgres — поэтому проверяем подстрокой
    ddl = " ".join(check_names())
    assert "ck_criterion_ratings_score" in ddl
    assert "ck_criterion_ratings_score_1_10" not in ddl
