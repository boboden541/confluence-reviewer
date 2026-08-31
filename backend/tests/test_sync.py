"""Тесты синхронизации страниц (ФТ-CR-3..ФТ-CR-6) на фейковом клиенте."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from app.clients.confluence import ConfluenceError, PageContent, PageSummary
from app.database import Base, SessionLocal, engine
from app.models import Analyst, ConfluenceDocument
from app.services import sync as sync_module
from app.utils import now_utc


def run(coro):
    return asyncio.run(coro)


def make_summary(page_id: str, title: str, modified: bool = False) -> PageSummary:
    ts = now_utc() - (timedelta(days=1) if not modified else timedelta(days=-1))
    return PageSummary(
        page_id=page_id,
        title=title,
        url=f"https://conf.test/pages/{page_id}",
        created_at=now_utc() - timedelta(days=30),
        last_modified_at=ts,
    )


def make_content(summary: PageSummary) -> PageContent:
    return PageContent(
        page_id=summary.page_id,
        title=summary.title,
        url=summary.url,
        content_html=f"<h1>Введение</h1><p>{summary.title}</p>",
        created_at=summary.created_at,
        last_modified_at=summary.last_modified_at,
    )


class FakeClient:
    """Клиент с фиксированным набором страниц: username 'raaliev' (не email!).

    Состояние — на уровне класса, чтобы тесты настраивали его до запуска синхронизации.
    """

    fetch_log: list[str] = []
    summaries: dict[str, list[PageSummary]] = {}
    fail_search: bool = False

    def __init__(self, settings):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def search_pages(self, creator: str) -> list[PageSummary]:
        if FakeClient.fail_search:
            raise ConfluenceError("Confluence недоступен", status_code=503)
        return FakeClient.summaries.get(creator, [])

    async def get_page(self, page_id: str) -> PageContent:
        FakeClient.fetch_log.append(page_id)
        for pages in FakeClient.summaries.values():
            for s in pages:
                if s.page_id == page_id:
                    return make_content(s)
        raise AssertionError(f"неожиданная страница {page_id}")


@pytest.fixture()
def db():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        yield session
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def fake_client(monkeypatch, db):
    FakeClient.fetch_log = []
    FakeClient.summaries = {}
    FakeClient.fail_search = False
    monkeypatch.setattr(sync_module, "ConfluenceClient", FakeClient)
    return FakeClient


def seed_analyst(db) -> Analyst:
    analyst = Analyst(full_name="Алиев Рустам", email="raaliev@mts.ru")
    db.add(analyst)
    db.commit()
    return analyst


def test_sync_creates_documents(db, fake_client):
    analyst = seed_analyst(db)
    FakeClient.summaries["raaliev"] = [
        make_summary("101", "Страница A"),
        make_summary("102", "Страница B"),
    ]

    result = run(sync_module.sync_analyst(analyst.id))

    assert result.created == 2 and result.error is None
    docs = db.query(ConfluenceDocument).order_by(ConfluenceDocument.confluence_page_id).all()
    assert [d.confluence_page_id for d in docs] == ["101", "102"]
    assert all("<h1>Введение</h1>" in d.content_html for d in docs)  # контент догружен
    assert set(FakeClient.fetch_log) == {"101", "102"}
    db.refresh(analyst)
    assert analyst.last_synced_at is not None and analyst.sync_error is None


def test_sync_unchanged_pages_skip_content_fetch(db, fake_client):
    analyst = seed_analyst(db)
    FakeClient.summaries["raaliev"] = [
        make_summary("101", "Страница A"),
        make_summary("102", "Страница B"),
    ]
    run(sync_module.sync_analyst(analyst.id))
    FakeClient.fetch_log = []  # чистим лог между прогонами

    result = run(sync_module.sync_analyst(analyst.id))  # повторная синхронизация

    assert result.created == 0 and result.updated == 2
    assert FakeClient.fetch_log == []  # содержимое не перезагружалось (экономия запросов)


def test_sync_modified_page_refetches_content(db, fake_client):
    analyst = seed_analyst(db)
    FakeClient.summaries["raaliev"] = [
        make_summary("101", "Страница A"),
        make_summary("102", "Страница B"),
    ]
    run(sync_module.sync_analyst(analyst.id))
    FakeClient.fetch_log = []

    # Страница 102 изменилась в Confluence, 101 — нет (тот же объект с теми же датами)
    unchanged_101 = FakeClient.summaries["raaliev"][0]
    FakeClient.summaries["raaliev"] = [
        unchanged_101,
        make_summary("102", "Страница B (обновлена)", modified=True),
    ]
    result = run(sync_module.sync_analyst(analyst.id))

    assert FakeClient.fetch_log == ["102"]
    doc = db.query(ConfluenceDocument).filter_by(confluence_page_id="102").one()
    assert "обновлена" in doc.content_html


def test_sync_api_failure_saved_as_error(db, fake_client):
    analyst = seed_analyst(db)
    FakeClient.fail_search = True

    result = run(sync_module.sync_analyst(analyst.id))

    assert result.error is not None
    db.refresh(analyst)
    assert analyst.sync_error is not None


def test_sync_all_analysts(db, fake_client):
    db.add_all(
        [
            Analyst(full_name="А", email="raaliev@mts.ru"),
            Analyst(full_name="Б", email="nikulinva@mts.ru"),
        ]
    )
    db.commit()
    FakeClient.summaries["raaliev"] = [make_summary("1", "A")]
    FakeClient.summaries["nikulinva"] = [make_summary("2", "B")]

    results = run(sync_module.sync_all())

    assert len(results) == 2
    assert all(r.error is None for r in results)
    assert db.query(ConfluenceDocument).count() == 2


def test_sync_modified_page_resets_validation_status(db, fake_client):
    """Изменившаяся страница сбрасывает прошлую проверку (замечание №3).

    Неизменившиеся документы сохраняют статус и дату проверки.
    """
    analyst = seed_analyst(db)
    FakeClient.summaries["raaliev"] = [
        make_summary("101", "Страница A"),
        make_summary("102", "Страница B"),
    ]
    run(sync_module.sync_analyst(analyst.id))

    checked_at = now_utc()
    for page_id in ("101", "102"):
        doc = db.query(ConfluenceDocument).filter_by(confluence_page_id=page_id).one()
        doc.validation_status = "failed"
        doc.last_validated_at = checked_at
    db.commit()

    # 102 изменилась, 101 — нет
    unchanged_101 = FakeClient.summaries["raaliev"][0]
    FakeClient.summaries["raaliev"] = [
        unchanged_101,
        make_summary("102", "Страница B (обновлена)", modified=True),
    ]
    run(sync_module.sync_analyst(analyst.id))

    db.expire_all()  # объекты читались до коммита синхронизации в другой сессии
    stale = db.query(ConfluenceDocument).filter_by(confluence_page_id="102").one()
    assert stale.validation_status == "not_checked"
    assert stale.last_validated_at is None

    fresh = db.query(ConfluenceDocument).filter_by(confluence_page_id="101").one()
    assert fresh.validation_status == "failed"
    assert fresh.last_validated_at == checked_at
