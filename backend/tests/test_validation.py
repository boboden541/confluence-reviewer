"""Тесты оркестрации валидации: статусы, идемпотентность, ошибки (ФТ-CR-12..16)."""

from __future__ import annotations

import time
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.database import Base, SessionLocal, engine
from app.models import Analyst, ConfluenceDocument, TriggerType, ValidationStatus
from app.services import tasks
from app.services.ai_validator import AIValidationError, AIValidationResult
from app.services.validation import DocumentNotFound, run_validation
from app.utils import now_utc


@pytest.fixture(autouse=True)
def _db():
    """Сервисные тесты работают с БД напрямую — таблицы нужны и без client."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def h(level: int, text: str) -> str:
    return f"<h{level}>{text}</h{level}>"


GOOD_BODY = "".join(
    [
        h(1, "Введение"),
        h(2, "Общая информация"),
        h(1, "Общее описание"),
        h(2, "Назначение документа"),
        h(2, "Контекст"),
        h(1, "Функциональные требования (BackEnd)"),
        h(2, "Создать таблицу-справочник"),
        h(3, "Общее описание"),
        h(3, "Описание доработок"),
        h(3, "Критерии приёмки"),
        h(3, "Документация по функционалу"),
        h(1, "Требования к интерфейсам"),
        h(2, "Сценарии использования"),
        h(1, "Ревью требований"),
    ]
)


def seed_document(body: str = GOOD_BODY, title: str = "[СТ] Доработка") -> int:
    with SessionLocal() as db:
        analyst = Analyst(full_name="Тест", email="v@mts.ru")
        db.add(analyst)
        db.flush()
        doc = ConfluenceDocument(
            analyst_id=analyst.id,
            confluence_page_id=str(now_utc().timestamp()).replace(".", ""),
            title=title,
            url="https://conf.test/pages/x",
            content_html=body,
            last_modified_in_confluence_at=now_utc(),
        )
        db.add(doc)
        db.commit()
        return doc.id


class FakeAIValidator:
    """Подмена ИИ-валидатора: считает вызовы, может возвращать ошибку."""

    calls = 0
    result = AIValidationResult(
        passed=True, summary="ok", findings_markdown="✅ Замечаний нет.",
        findings_count=0, model="test",
    )
    error: AIValidationError | None = None

    def validate(self, title: str, markdown: str) -> AIValidationResult:
        type(self).calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def patch_ai(monkeypatch, passed=True, error=None):
    FakeAIValidator.calls = 0
    FakeAIValidator.error = error
    FakeAIValidator.result = AIValidationResult(
        passed=passed,
        summary="итог",
        findings_markdown="✅ ок" if passed else "- ❌ **[полнота, critical]** пробел",
        findings_count=0 if passed else 1,
        model="test",
    )
    monkeypatch.setattr("app.services.validation.AIValidator", FakeAIValidator)


def doc_by_id(doc_id: int) -> ConfluenceDocument:
    with SessionLocal() as db:
        return db.get(ConfluenceDocument, doc_id)


# --- run_validation: статусы ---


def test_validation_passed(monkeypatch):
    patch_ai(monkeypatch, passed=True)
    doc_id = seed_document()
    report = run_validation(doc_id)
    assert report.overall_passed and report.template_passed and report.ai_passed
    assert report.triggered_by == TriggerType.MANUAL
    assert "✅" in report.template_findings
    doc = doc_by_id(doc_id)
    assert doc.validation_status == ValidationStatus.PASSED
    assert doc.last_validated_at is not None


def test_validation_failed_when_template_fails(monkeypatch):
    patch_ai(monkeypatch, passed=True)
    doc_id = seed_document(body="<h1>Не по шаблону</h1>", title="Без маркера")
    report = run_validation(doc_id)
    assert not report.overall_passed
    assert not report.template_passed and report.ai_passed
    assert doc_by_id(doc_id).validation_status == ValidationStatus.FAILED


def test_validation_failed_when_ai_fails(monkeypatch):
    patch_ai(monkeypatch, passed=False)
    doc_id = seed_document()
    report = run_validation(doc_id)
    assert not report.overall_passed
    assert report.template_passed and not report.ai_passed
    assert doc_by_id(doc_id).validation_status == ValidationStatus.FAILED


def test_ai_technical_error_sets_error_status(monkeypatch):
    patch_ai(monkeypatch, error=AIValidationError("Нет связи с ИИ"))
    doc_id = seed_document()
    report = run_validation(doc_id)
    assert report.error_message == "Нет связи с ИИ"
    doc = doc_by_id(doc_id)
    assert doc.validation_status == ValidationStatus.ERROR
    assert doc.last_validated_at is None  # ошибка != успешная валидация

    # повторный запуск после устранения сбоя проходит (ФТ-CR-15)
    patch_ai(monkeypatch, passed=True)
    report2 = run_validation(doc_id)
    assert report2.overall_passed
    assert doc_by_id(doc_id).validation_status == ValidationStatus.PASSED


# --- идемпотентность (ФТ-CR-14) ---


def test_unchanged_document_not_revalidated(monkeypatch):
    patch_ai(monkeypatch, passed=True)
    doc_id = seed_document()
    first = run_validation(doc_id)
    second = run_validation(doc_id)
    assert FakeAIValidator.calls == 1
    assert second.id == first.id  # тот же отчёт, без нового вызова ИИ


def test_modified_document_revalidated(monkeypatch):
    patch_ai(monkeypatch, passed=True)
    doc_id = seed_document()
    run_validation(doc_id)
    with SessionLocal() as db:
        doc = db.get(ConfluenceDocument, doc_id)
        doc.last_modified_in_confluence_at = now_utc() + timedelta(minutes=1)
        db.commit()
    run_validation(doc_id)
    assert FakeAIValidator.calls == 2


def test_force_revalidates_even_unchanged(monkeypatch):
    patch_ai(monkeypatch, passed=True)
    doc_id = seed_document()
    first = run_validation(doc_id)
    second = run_validation(doc_id, force=True)
    assert FakeAIValidator.calls == 2
    assert second.id != first.id


def test_document_not_found():
    try:
        run_validation(999999)
    except DocumentNotFound:
        pass
    else:
        raise AssertionError("ожидали DocumentNotFound")


# --- автозапуск после синхронизации (ФТ-CR-12) ---


def test_start_validations_for_changed_docs(monkeypatch):
    calls: list[tuple] = []

    def fake_start(doc_id, *, trigger, force=False):
        calls.append((doc_id, trigger))
        return True, "ok"

    monkeypatch.setattr(tasks, "start_validation", fake_start)
    results = [
        tasks.SyncResult(analyst_id=1, analyst_name="A", changed_document_ids=[10, 11]),
        tasks.SyncResult(analyst_id=2, analyst_name="B"),  # без изменений
        tasks.SyncResult(analyst_id=3, analyst_name="C", error="нет связи", changed_document_ids=[12]),
    ]
    started = tasks.start_validations_for(results)
    assert started == [10, 11]
    assert calls[0] == (10, TriggerType.AUTO)
    assert calls[1] == (11, TriggerType.AUTO)


# --- API: ручной запуск и получение отчёта (ФТ-CR-13, ФТ-CR-16) ---


def test_validate_endpoint_202_and_report(client, monkeypatch):
    doc_id = seed_document()

    def fake_run(document_id, *, trigger, force=False):
        return SimpleNamespace(id=77)

    monkeypatch.setattr(tasks, "run_validation", fake_run)
    resp = client.post(f"/api/documents/{doc_id}/validate")
    assert resp.status_code == 202

    for _ in range(50):
        state = tasks.validation_status().get(doc_id, {})
        if state.get("status") in {"done", "error", "not_found"}:
            break
        time.sleep(0.05)
    assert state["status"] == "done"
    assert state["report_id"] == 77


def test_validate_endpoint_conflict_while_running(client, monkeypatch):
    doc_id = seed_document()
    monkeypatch.setitem(
        tasks._validation_state, doc_id, {"status": "running", "started_at": None, "error": None}
    )
    resp = client.post(f"/api/documents/{doc_id}/validate")
    assert resp.status_code == 409


def test_validate_endpoint_not_found(client):
    assert client.post("/api/documents/99999/validate").status_code == 404


def test_report_endpoint(monkeypatch, client):
    patch_ai(monkeypatch, passed=True)
    doc_id = seed_document()
    report = run_validation(doc_id)

    resp = client.get(f"/api/documents/{doc_id}/report")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == report.id
    assert body["overall_passed"] is True
    assert body["triggered_by"] == "manual"
    assert "✅" in body["template_findings"]
    assert "✅" in body["ai_findings"]


def test_report_endpoint_empty_and_not_found(client):
    doc_id = seed_document(body="<h1>Что-то</h1>")
    assert client.get(f"/api/documents/{doc_id}/report").status_code == 404
    assert client.get("/api/documents/99999/report").status_code == 404
