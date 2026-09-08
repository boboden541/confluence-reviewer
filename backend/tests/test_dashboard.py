"""Тесты главной страницы: очередь внимания (/api/dashboard) и лента событий
(/api/dashboard/feed).

Приоритет секций: провал/ошибка → устарел после правки → ждёт оценки;
документ попадает только в первую подходящую секцию.
"""

from __future__ import annotations

from datetime import timedelta

from app.database import Base, SessionLocal, engine
from app.models import (
    AiCriterion,
    Analyst,
    ConfluenceDocument,
    CriterionRating,
    Team,
    TriggerType,
    ValidationReport,
    ValidationStatus,
)
from app.usecase import tasks
from app.utils import now_utc

import pytest


@pytest.fixture(autouse=True)
def _db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _journal():
    tasks._event_journal.clear()
    yield
    tasks._event_journal.clear()


def _analyst(**overrides) -> Analyst:
    data = {
        "full_name": "Алиев Рустам",
        "email": f"dash-{now_utc().timestamp()}-{id(object())}@company.ru",
    }
    data.update(overrides)
    with SessionLocal() as db:
        analyst = Analyst(**data)
        db.add(analyst)
        db.commit()
        db.refresh(analyst)
        return analyst


def _team() -> int:
    with SessionLocal() as db:
        from app.models import Cluster

        cluster = Cluster(name=f"Кластер {now_utc().timestamp()}")
        db.add(cluster)
        db.flush()
        team = Team(cluster_id=cluster.id, name=f"GDS {now_utc().timestamp()}")
        db.add(team)
        db.commit()
        db.refresh(team)
        return team.id


def _criterion() -> int:
    with SessionLocal() as db:
        criterion = AiCriterion(
            code=f"crit_{str(now_utc().timestamp()).replace('.', '')}",
            name=f"Критерий {now_utc().timestamp()}",
            prompt="проверка",
        )
        db.add(criterion)
        db.commit()
        db.refresh(criterion)
        return criterion.id


def _doc(analyst_id: int, *, status=ValidationStatus.NOT_CHECKED, title="Документ",
         modified=None, validated=None) -> int:
    with SessionLocal() as db:
        doc = ConfluenceDocument(
            analyst_id=analyst_id,
            confluence_page_id=str(now_utc().timestamp()).replace(".", "") + str(id(object())),
            title=title,
            url="https://conf.test/x",
            content_html="<h1>Введение</h1>",
            validation_status=status,
            last_modified_in_confluence_at=modified,
            last_validated_at=validated,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc.id


def _report(document_id: int, *, ai_passed=None, template_passed=None,
            error_message=None, created=None) -> int:
    with SessionLocal() as db:
        report = ValidationReport(
            document_id=document_id,
            triggered_by=TriggerType.MANUAL,
            ai_passed=ai_passed,
            template_passed=template_passed,
            error_message=error_message,
            created_at=created or now_utc(),
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        return report.id


def _section(sections: list[dict], type_: str) -> dict:
    return next(s for s in sections if s["type"] == type_)


def _doc_ids(section: dict) -> set[int]:
    return {item["document_id"] for item in section["items"]}


# --- пустая база ---


def test_empty_db_returns_zero_sections(client):
    body = client.get("/api/dashboard").json()
    types = {s["type"]: s for s in body["sections"]}
    assert set(types) == {"failed", "stale", "ratings", "no_team", "references"}
    # в тестовом env нет критериев и не настроен ИИ — обе записи честные
    refs = types["references"]
    assert {i["key"] for i in refs["items"]} <= {"no-ai-connection", "no-active-criteria"}
    others = [s for s in body["sections"] if s["type"] != "references"]
    assert all(s["total"] == 0 and s["items"] == [] for s in others)


# --- проваленные проверки ---


def test_failed_document_lands_in_failed_section(client):
    analyst = _analyst()
    doc_id = _doc(analyst.id, status=ValidationStatus.FAILED, title="Провальный")
    _report(doc_id, ai_passed=False, template_passed=True)

    body = client.get("/api/dashboard").json()
    failed = _section(body["sections"], "failed")
    assert failed["total"] == 1
    assert _doc_ids(failed) == {doc_id}
    item = failed["items"][0]
    assert item["title"] == "Провальный"
    assert "ИИ-проверка" in item["subtitle"]
    assert item["document_id"] == doc_id
    assert item["at"] is not None


def test_error_report_subtitle_mentions_retry(client):
    analyst = _analyst()
    doc_id = _doc(analyst.id, status=ValidationStatus.ERROR)
    _report(doc_id, error_message="Нет связи с ИИ")

    body = client.get("/api/dashboard").json()
    item = _section(body["sections"], "failed")["items"][0]
    assert "техническая ошибка" in item["subtitle"]


def test_template_and_ai_failures_combined_subtitle(client):
    analyst = _analyst()
    doc_id = _doc(analyst.id, status=ValidationStatus.FAILED)
    _report(doc_id, ai_passed=False, template_passed=False)

    body = client.get("/api/dashboard").json()
    item = _section(body["sections"], "failed")["items"][0]
    assert "шаблон и ИИ-проверка" in item["subtitle"]


def test_failed_sorted_by_recency(client):
    analyst = _analyst()
    old = _doc(analyst.id, status=ValidationStatus.FAILED, title="Старый")
    _report(old, ai_passed=False, created=now_utc() - timedelta(hours=2))
    new = _doc(analyst.id, status=ValidationStatus.FAILED, title="Свежий")
    _report(new, ai_passed=False, created=now_utc())

    body = client.get("/api/dashboard").json()
    items = _section(body["sections"], "failed")["items"]
    assert [i["title"] for i in items] == ["Свежий", "Старый"]


# --- устаревшие после правок ---


def test_stale_document_with_history(client):
    analyst = _analyst()
    doc_id = _doc(
        analyst.id,
        status=ValidationStatus.NOT_CHECKED,
        modified=now_utc(),
        validated=now_utc() - timedelta(days=1),
    )
    _report(doc_id, ai_passed=True)  # успешная проверка была

    body = client.get("/api/dashboard").json()
    stale = _section(body["sections"], "stale")
    assert stale["total"] == 1
    assert _doc_ids(stale) == {doc_id}


def test_never_checked_document_not_in_stale(client):
    analyst = _analyst()
    _doc(analyst.id, status=ValidationStatus.NOT_CHECKED)  # проверок не было

    body = client.get("/api/dashboard").json()
    assert _section(body["sections"], "stale")["total"] == 0


# --- ждут оценки ---


def test_ai_passed_without_ratings_is_awaiting(client):
    analyst = _analyst()
    doc_id = _doc(analyst.id, status=ValidationStatus.PASSED)
    _report(doc_id, ai_passed=True, template_passed=True)

    body = client.get("/api/dashboard").json()
    ratings = _section(body["sections"], "ratings")
    assert ratings["total"] == 1
    assert _doc_ids(ratings) == {doc_id}


def test_fresh_rating_removes_from_awaiting(client):
    analyst = _analyst()
    doc_id = _doc(analyst.id, status=ValidationStatus.PASSED)
    criterion_id = _criterion()
    _report(doc_id, ai_passed=True, created=now_utc() - timedelta(hours=1))
    with SessionLocal() as db:
        db.add(CriterionRating(document_id=doc_id, criterion_id=criterion_id, score=8))
        db.commit()

    body = client.get("/api/dashboard").json()
    assert _section(body["sections"], "ratings")["total"] == 0


def test_stale_rating_returns_to_awaiting(client):
    """Оценка старше нового прогона — документ снова ждёт руководителя."""
    analyst = _analyst()
    doc_id = _doc(analyst.id, status=ValidationStatus.PASSED)
    criterion_id = _criterion()
    with SessionLocal() as db:
        db.add(
            CriterionRating(
                document_id=doc_id,
                criterion_id=criterion_id,
                score=8,
                updated_at=now_utc() - timedelta(hours=2),
            )
        )
        db.commit()
    _report(doc_id, ai_passed=True, created=now_utc())  # прогон новее оценки

    body = client.get("/api/dashboard").json()
    assert _doc_ids(_section(body["sections"], "ratings")) == {doc_id}


def test_not_checked_document_not_in_ratings(client):
    """Приоритет забот: устаревшему документу сперва нужна перепроверка,
    а не оценка старого прогона; проваленный ИИ-прогон оцениваемо — он в
    ratings наравне с пройденным."""
    analyst = _analyst()
    doc_id = _doc(
        analyst.id,
        status=ValidationStatus.NOT_CHECKED,
        modified=now_utc(),
        validated=now_utc() - timedelta(days=1),
    )
    _report(doc_id, ai_passed=True)  # старый состоявшийся ИИ-прогон

    body = client.get("/api/dashboard").json()
    assert _doc_ids(_section(body["sections"], "ratings")) == set()
    assert _doc_ids(_section(body["sections"], "stale")) == {doc_id}


# --- аналитики без команды ---


def test_analyst_without_team_listed_with_documents_count(client):
    analyst = _analyst()
    _doc(analyst.id)

    body = client.get("/api/dashboard").json()
    no_team = _section(body["sections"], "no_team")
    assert no_team["total"] == 1
    item = no_team["items"][0]
    assert item["title"] == analyst.full_name
    assert item["analyst_id"] == analyst.id
    assert "1 документ" in item["subtitle"]


def test_teamed_analyst_not_listed(client):
    analyst = _analyst()
    team_id = _team()
    with SessionLocal() as db:
        db.get(Analyst, analyst.id).team_id = team_id
        db.commit()

    body = client.get("/api/dashboard").json()
    assert _section(body["sections"], "no_team")["total"] == 0


# --- справочники ---


def test_reference_problems_listed(client):
    # шаблон без активной версии (контейнер без версий) + нет активных критериев
    with SessionLocal() as db:
        from app.models import Template

        db.add(Template())
        db.commit()

    body = client.get("/api/dashboard").json()
    refs = _section(body["sections"], "references")
    titles = {i["title"] for i in refs["items"]}
    assert any("без активной версии" in t for t in titles)
    assert any("ИИ-критериев" in t for t in titles)
    # у каждого item — маршрут настройки
    assert all(i["section"] for i in refs["items"])


# --- лимит секции ---


def test_section_limit_keeps_total_accurate(client):
    analyst = _analyst()
    for i in range(10):
        doc_id = _doc(analyst.id, status=ValidationStatus.FAILED, title=f"Док {i}")
        _report(doc_id, ai_passed=False)

    body = client.get("/api/dashboard").json()
    failed = _section(body["sections"], "failed")
    assert failed["total"] == 10
    assert len(failed["items"]) == 8  # SECTION_LIMIT


# --- лента событий ---


def test_feed_serves_journal_even_without_subscribers(client):
    # подписчиков нет — журнал всё равно пополняется
    tasks._publish_event("validation", {"document_id": 1, "status": "done", "report_id": 9})
    tasks._publish_event("sync", {"running": False})

    body = client.get("/api/dashboard/feed").json()
    assert len(body) == 2
    assert body[0]["type"] == "sync"  # свежие сверху
    assert body[1]["type"] == "validation"
    assert body[1]["payload"]["document_id"] == 1
    assert body[1]["at"] is not None


def test_feed_limit(client):
    for i in range(40):
        tasks._publish_event("validation", {"document_id": i, "status": "done"})
    body = client.get("/api/dashboard/feed?limit=10").json()
    assert len(body) == 10
