"""Тесты публикации замечаний комментарием в Confluence (ФТ-CR-17)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from app.clients.confluence import ConfluenceError
from app.database import Base, SessionLocal, engine
from app.models import Analyst, ConfluenceDocument, TriggerType, ValidationReport
from app.services.comments import (
    CommentError,
    NoReportError,
    build_comment,
    publish_report_comment,
)
from app.services.validation import DocumentNotFound
from app.utils import now_utc


@pytest.fixture(autouse=True)
def _db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def seed_doc_with_report(
    *,
    template_passed: bool | None = True,
    ai_passed=True,
    error=None,
    comment_sent_at=None,
) -> tuple[int, int]:
    """(document_id, report_id). template_passed=None — проверка не запускалась."""
    with SessionLocal() as db:
        analyst = Analyst(full_name="Тест", email="c@mts.ru")
        db.add(analyst)
        db.flush()
        doc = ConfluenceDocument(
            analyst_id=analyst.id,
            confluence_page_id="424242",
            title="[СТ] Доработка",
            url="https://conf.test/pages/viewpage.action?pageId=424242",
            content_html="<h1>Введение</h1>",
        )
        db.add(doc)
        db.flush()
        if template_passed is None:
            template_findings = ""  # проверка не запускалась
        else:
            template_findings = (
                "✅ Шаблон ок" if template_passed else "### ❌ Критичные замечания\n- ❌ нет раздела"
            )
        report = ValidationReport(
            document_id=doc.id,
            triggered_by=TriggerType.MANUAL,
            template_passed=template_passed,
            template_findings=template_findings,
            ai_passed=ai_passed,
            ai_findings="✅ Замечаний нет" if ai_passed else "- ❌ **[полнота, critical]** пробел",
            overall_passed=bool(
                (template_passed is None or template_passed)
                and (ai_passed is None or ai_passed)
                and not error
            ),
            error_message=error,
            comment_sent_at=comment_sent_at,
        )
        db.add(report)
        db.commit()
        return doc.id, report.id


class FakeConfluenceClient:
    """Записывает вызовы add_comment; может поднимать ошибку."""

    comments: list[tuple[str, str]] = []
    error: ConfluenceError | None = None

    def __init__(self, settings=None):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def add_comment(self, page_id: str, text: str) -> None:
        if self.error is not None:
            raise self.error
        type(self).comments.append((page_id, text))


@pytest.fixture()
def fake_client(monkeypatch):
    FakeConfluenceClient.comments = []
    FakeConfluenceClient.error = None
    monkeypatch.setattr("app.services.comments.ConfluenceClient", FakeConfluenceClient)
    return FakeConfluenceClient


# --- текст комментария ---


def test_build_comment_contains_both_parts():
    with SessionLocal() as db:
        doc = db.get(ConfluenceDocument, seed_doc_with_report()[0])
        report = db.query(ValidationReport).first()
        text = build_comment(report, doc)
    assert "«[СТ] Доработка»" in text
    assert "✅ Соответствие шаблону" in text
    assert "✅ Качество содержимого" in text
    assert "✅ Шаблон ок" in text
    assert "✅ Замечаний нет" in text
    assert "ручной" in text


def test_build_comment_failed_report():
    doc_id, _ = seed_doc_with_report(template_passed=False, ai_passed=False)
    with SessionLocal() as db:
        doc = db.get(ConfluenceDocument, doc_id)
        report = db.query(ValidationReport).first()
        text = build_comment(report, doc)
    assert "❌ Соответствие шаблону" in text
    assert "❌ Качество содержимого" in text
    assert "нет раздела" in text
    assert "critical" in text


def test_build_comment_skips_template_block_when_not_run():
    """Проверка шаблона не запускалась (NULL в отчёте) — блока шаблона в комментарии нет."""
    doc_id, _ = seed_doc_with_report(template_passed=None)
    with SessionLocal() as db:
        doc = db.get(ConfluenceDocument, doc_id)
        report = db.query(ValidationReport).first()
        text = build_comment(report, doc)
    assert "Соответствие шаблону" not in text
    assert "Качество содержимого" in text


# --- публикация ---


def test_publish_ok(fake_client):
    doc_id, report_id = seed_doc_with_report()
    report = asyncio.run(publish_report_comment(doc_id))
    assert len(fake_client.comments) == 1
    page_id, text = fake_client.comments[0]
    assert page_id == "424242"
    assert "Автоматическая проверка" in text
    assert report.comment_sent_at is not None
    assert report.id == report_id


def test_publish_twice_conflicts(fake_client):
    doc_id, _ = seed_doc_with_report()
    asyncio.run(publish_report_comment(doc_id))
    with pytest.raises(CommentError, match="уже опубликован"):
        asyncio.run(publish_report_comment(doc_id))
    assert len(fake_client.comments) == 1  # дубль не отправлен


def test_publish_no_report(fake_client):
    with SessionLocal() as db:
        analyst = Analyst(full_name="Т", email="n@mts.ru")
        db.add(analyst)
        db.flush()
        doc = ConfluenceDocument(
            analyst_id=analyst.id, confluence_page_id="1", title="t", url="u", content_html=""
        )
        db.add(doc)
        db.commit()
        doc_id = doc.id
    with pytest.raises(NoReportError):
        asyncio.run(publish_report_comment(doc_id))
    assert fake_client.comments == []


def test_publish_error_report_conflicts(fake_client):
    doc_id, _ = seed_doc_with_report(error="ИИ недоступен")
    with pytest.raises(CommentError, match="техническую ошибку"):
        asyncio.run(publish_report_comment(doc_id))
    assert fake_client.comments == []


def test_publish_document_not_found(fake_client):
    with pytest.raises(DocumentNotFound):
        asyncio.run(publish_report_comment(999999))


def test_publish_confluence_failure(fake_client):
    fake_client.error = ConfluenceError("Confluence API 403: нет прав")
    doc_id, report_id = seed_doc_with_report()
    with pytest.raises(ConfluenceError):
        asyncio.run(publish_report_comment(doc_id))
    with SessionLocal() as db:  # отметка не выставлена — можно повторить
        assert db.get(ValidationReport, report_id).comment_sent_at is None


# --- API ---


def test_comment_endpoint_ok(client, fake_client):
    doc_id, _ = seed_doc_with_report()
    resp = client.post(f"/api/documents/{doc_id}/comment")
    assert resp.status_code == 200
    assert resp.json()["comment_sent_at"] is not None
    assert len(fake_client.comments) == 1


def test_comment_endpoint_conflict_on_repeat(client, fake_client):
    doc_id, _ = seed_doc_with_report()
    assert client.post(f"/api/documents/{doc_id}/comment").status_code == 200
    resp = client.post(f"/api/documents/{doc_id}/comment")
    assert resp.status_code == 409


def test_comment_endpoint_no_report_404(client, fake_client):
    with SessionLocal() as db:
        analyst = Analyst(full_name="Т", email="e@mts.ru")
        db.add(analyst)
        db.flush()
        doc = ConfluenceDocument(
            analyst_id=analyst.id, confluence_page_id="2", title="t", url="u", content_html=""
        )
        db.add(doc)
        db.commit()
        doc_id = doc.id
    assert client.post(f"/api/documents/{doc_id}/comment").status_code == 404
    assert client.post("/api/documents/99999/comment").status_code == 404


def test_comment_endpoint_confluence_502(client, fake_client):
    fake_client.error = ConfluenceError("Confluence API 500: boom", status_code=500)
    doc_id, _ = seed_doc_with_report()
    resp = client.post(f"/api/documents/{doc_id}/comment")
    assert resp.status_code == 502


def test_report_schema_exposes_comment_sent_at(client, fake_client):
    doc_id, _ = seed_doc_with_report(comment_sent_at=now_utc() - timedelta(minutes=5))
    body = client.get(f"/api/documents/{doc_id}/report").json()
    assert body["comment_sent_at"] is not None
