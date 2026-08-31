"""Выборочная проверка: диалог настроек — шаблон + промт ИИ, batch-запуск.

Покрывает: GET /api/validation-config, опции одиночной проверки,
POST /api/documents/validate-batch, влияние промта на идемпотентность
и аудит «чем проверяли» в отчёте.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

from app.database import Base, SessionLocal, engine
from app.models import Analyst, ConfluenceDocument, ValidationStatus
from app.services import tasks
from app.services.ai_settings import AIConnection
from app.services.ai_validator import AIValidationResult, SYSTEM_PROMPT
from app.services.validation import run_validation
from app.utils import now_utc

import pytest


@pytest.fixture(autouse=True)
def _db():
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


def seed_document(title: str = "[СТ] Доработка", body: str = GOOD_BODY) -> int:
    with SessionLocal() as db:
        analyst = Analyst(
            full_name="Тест", email=f"sel-{now_utc().timestamp()}-{id(object())}@mts.ru"
        )
        db.add(analyst)
        db.flush()
        doc = ConfluenceDocument(
            analyst_id=analyst.id,
            confluence_page_id=str(now_utc().timestamp()).replace(".", ""),
            title=title,
            url="https://conf.test/pages/sel",
            content_html=body,
            last_modified_in_confluence_at=now_utc(),
        )
        db.add(doc)
        db.commit()
        return doc.id


class FakeAIValidator:
    """Подмена ИИ: запоминает промт каждого вызова, результат можно подменять."""

    calls = 0
    prompts: list[str | None] = []
    result = AIValidationResult(
        passed=True, summary="ok", findings_markdown="✅", findings_count=0, model="t"
    )

    def __init__(self, *args, **kwargs):
        pass  # продакшн-код передаёт connection= — фейку он не нужен

    def validate(self, title, markdown, system_prompt=None, expected_criteria=None):
        type(self).calls += 1
        type(self).prompts.append(system_prompt)
        return type(self).result


@pytest.fixture()
def fake_ai(monkeypatch):
    FakeAIValidator.calls = 0
    FakeAIValidator.prompts = []
    FakeAIValidator.result = AIValidationResult(
        passed=True, summary="ok", findings_markdown="✅", findings_count=0, model="t"
    )
    monkeypatch.setattr("app.services.validation.AIValidator", FakeAIValidator)
    # эффективная модель = модель фейка, иначе идемпотентность по модели (ФТ-CR-14)
    monkeypatch.setattr(
        "app.services.validation.get_ai_connection",
        lambda db: AIConnection(
            protocol="anthropic",
            base_url="https://ai.test",
            api_key="test-key",
            model="t",
            max_tokens=100,
            timeout_seconds=1.0,
        ),
    )
    return FakeAIValidator


def wait_bulk_done(timeout_s: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout_s
    st = tasks.bulk_status()
    while st["running"] and time.monotonic() < deadline:
        time.sleep(0.05)
        st = tasks.bulk_status()
    return st


# --- GET /api/validation-config ---


def test_validation_config_returns_active_template_and_default_prompt(client):
    body = client.get("/api/validation-config").json()
    assert body["default_prompt"] == SYSTEM_PROMPT
    assert "ревьюер технических требований" in body["default_prompt"]

    assert len(body["templates"]) == 1  # пока шаблон один; список — задел
    tpl = body["templates"][0]
    assert tpl["is_default"] is True
    assert tpl["section_count"] > 0
    assert "СТ" in tpl["name"]


# --- run_validation: промт и шаблон на запуск ---


def test_custom_prompt_reaches_ai_and_is_saved_in_report(client, fake_ai):
    doc_id = seed_document()
    custom = SYSTEM_PROMPT + "\n\nДополнительно: особое внимание к граничным случаям."
    report = run_validation(doc_id, ai_prompt=custom)
    assert fake_ai.prompts == [custom]
    assert report.ai_prompt == custom  # в отчёте — что реально применено


def test_assembled_prompt_not_saved_and_not_forced(client, fake_ai):
    """«Стандартный» промт теперь собирается из критериев справочника.

    Повторный запуск тем же набором — из кэша; промт, присланный дословно
    равным собранному, — тоже не override и не повод перепроверять.
    """
    doc_id = seed_document()
    first = run_validation(doc_id)  # промт собран из активных критериев
    assembled = fake_ai.prompts[0]
    assert "Полнота описания" in assembled
    second = run_validation(doc_id, ai_prompt=assembled)
    assert fake_ai.calls == 1
    assert second.id == first.id
    assert second.ai_prompt is None


def test_custom_prompt_forces_revalidation_of_unchanged_doc(client, fake_ai):
    doc_id = seed_document()
    first = run_validation(doc_id)
    custom = SYSTEM_PROMPT.replace("опытный", "внимательный")
    second = run_validation(doc_id, ai_prompt=custom)
    assert fake_ai.calls == 2  # изменённый промт обходит идемпотентность
    assert second.id != first.id
    assert second.ai_prompt == custom


def test_blank_prompt_is_ignored(client, fake_ai):
    doc_id = seed_document()
    report = run_validation(doc_id, ai_prompt="   ")
    assert report.ai_prompt is None
    # пустая строка = собранный промт, а не легаси-SYSTEM_PROMPT
    assert "Полнота описания" in fake_ai.prompts[0]


def test_specific_template_version_is_used(client, fake_ai):
    """Проверка идёт по выбранной версии шаблона, а не только по активной."""
    doc_id = seed_document(title="GDS-42 Изменение")  # маркер СТ не совпадает
    # активная версия (сеется из файла) требует маркер СТ → шаблон не пройден
    fail_report = run_validation(doc_id)
    assert fail_report.template_passed is False

    # сохраняем вторую версию с маркером GDS и одним обязательным разделом
    assert (
        client.put(
            "/api/template",
            json={
                "title_marker": "GDS",
                "sections": [{"level": 1, "text": "Введение", "required": True, "aliases": []}],
            },
        ).status_code
        == 200
    )
    versions = client.get("/api/template/versions").json()
    old_version_id = next(v["id"] for v in versions if not v["is_active"])

    # документ не менялся, но force: по старой версии снова провал, по новой — пройден
    pass_report = run_validation(doc_id, force=True)
    assert pass_report.template_passed is True
    assert pass_report.template_version_id == versions[0]["id"]  # активная (новая)

    fail_by_choice = run_validation(doc_id, force=True, template_version_id=old_version_id)
    assert fail_by_choice.template_passed is False  # выбранная версия реально применена
    assert fail_by_choice.template_version_id == old_version_id


# --- API: одиночный запуск с телом-опциями ---


def test_validate_endpoint_accepts_options_body(client, monkeypatch):
    doc_id = seed_document()
    captured: dict = {}

    def fake_run(document_id, *, trigger, force=False, template_version_id=None, ai_prompt=None, checks=None, criterion_ids=None):
        captured.update(
            template=template_version_id, prompt=ai_prompt, doc=document_id, checks=checks
        )
        return SimpleNamespace(id=9)

    monkeypatch.setattr(tasks, "run_validation", fake_run)
    resp = client.post(
        f"/api/documents/{doc_id}/validate?force=true",
        json={"template_id": 1, "ai_prompt": "мой промт"},
    )
    assert resp.status_code == 202
    for _ in range(50):
        state = tasks.validation_status().get(doc_id, {})
        if state.get("status") in {"done", "error", "not_found"}:
            break
        time.sleep(0.05)
    assert captured == {"doc": doc_id, "template": 1, "prompt": "мой промт", "checks": None}


def test_validate_endpoint_without_body_still_works(client, monkeypatch):
    """Старые клиенты запускают проверку без тела — обратная совместимость."""
    doc_id = seed_document()
    monkeypatch.setattr(
        tasks, "run_validation", lambda document_id, **kw: SimpleNamespace(id=1)
    )
    assert client.post(f"/api/documents/{doc_id}/validate").status_code == 202


def test_validate_endpoint_unknown_template_404(client):
    doc_id = seed_document()
    resp = client.post(f"/api/documents/{doc_id}/validate", json={"template_id": 999})
    assert resp.status_code == 404
    assert "Шаблон" in resp.json()["detail"]


def test_blank_prompt_rejected_by_schema(client):
    doc_id = seed_document()
    resp = client.post(f"/api/documents/{doc_id}/validate", json={"ai_prompt": "  "})
    assert resp.status_code == 422


# --- POST /api/documents/validate-batch ---


def test_batch_runs_selected_documents_in_order(client, monkeypatch):
    ids = [seed_document() for _ in range(3)]
    seen: list[tuple[int, str | None, int | None]] = []

    async def fake_exec(document_id, trigger, force, template_version_id=None, ai_prompt=None, checks=None, criterion_ids=None):
        seen.append((document_id, ai_prompt, template_version_id))
        return SimpleNamespace(id=document_id)

    monkeypatch.setattr(tasks, "_execute_validation", fake_exec)
    chosen = [ids[2], ids[0], ids[2]]  # порядок сохраняется, дубль убирается
    resp = client.post(
        "/api/documents/validate-batch",
        json={"document_ids": chosen, "template_id": 1, "ai_prompt": "партийный промт"},
    )
    assert resp.status_code == 202
    assert resp.json()["total"] == 2

    st = wait_bulk_done()
    assert (st["done"], st["total"]) == (2, 2)
    assert seen == [(ids[2], "партийный промт", 1), (ids[0], "партийный промт", 1)]


def test_batch_missing_document_404(client):
    doc_id = seed_document()
    resp = client.post("/api/documents/validate-batch", json={"document_ids": [doc_id, 888888]})
    assert resp.status_code == 404
    assert "888888" in resp.json()["detail"]


def test_batch_empty_ids_and_bad_prompt_422(client):
    assert client.post("/api/documents/validate-batch", json={"document_ids": []}).status_code == 422
    doc_id = seed_document()
    assert (
        client.post("/api/documents/validate-batch", json={"document_ids": [doc_id], "ai_prompt": " \t "}).status_code
        == 422
    )


def test_batch_conflict_while_running(client, monkeypatch):
    doc_id = seed_document()

    async def slow_exec(document_id, trigger, force, template_version_id=None, ai_prompt=None, checks=None, criterion_ids=None):
        await asyncio.sleep(0.2)  # держим прогон открытым
        return SimpleNamespace(id=1)

    monkeypatch.setattr(tasks, "_execute_validation", slow_exec)
    assert client.post("/api/documents/validate-batch", json={"document_ids": [doc_id]}).status_code == 202
    assert client.post("/api/documents/validate-batch", json={"document_ids": [doc_id]}).status_code == 409
    wait_bulk_done()


# --- аудит в API отчёта ---


def test_report_exposes_template_and_prompt(client, fake_ai):
    doc_id = seed_document()
    run_validation(doc_id, ai_prompt="особый промт этой проверки")
    body = client.get(f"/api/documents/{doc_id}/report").json()
    assert body["ai_prompt"] == "особый промт этой проверки"
    assert body["template_version_id"] is not None


# --- выбор критериев проверки: checks (шаблон и/или наполнение) ---


def test_template_only_skips_ai(client, fake_ai):
    """Только шаблон: ИИ не вызывается, его поля в отчёте — NULL («не запускалась»)."""
    doc_id = seed_document()
    report = run_validation(doc_id, checks=["template"])
    assert fake_ai.calls == 0
    assert report.template_passed is True
    assert report.ai_passed is None
    assert report.ai_findings is None
    assert report.ai_model_used is None
    assert report.ai_prompt is None
    assert report.overall_passed is True  # итог = AND по запущенным
    assert report.template_version_id is not None


def test_ai_only_works_without_template(client, fake_ai, monkeypatch):
    """Только наполнение: работает даже если шаблон не настроен."""
    monkeypatch.setattr(
        "app.services.validation.get_template_for_validation", lambda db, vid: None
    )
    doc_id = seed_document()
    report = run_validation(doc_id, checks=["ai"])
    assert fake_ai.calls == 1
    assert report.template_passed is None
    assert report.template_findings == ""
    assert report.template_version_id is None
    assert report.ai_passed is True
    assert report.overall_passed is True


def test_template_only_without_template_errors(client, fake_ai, monkeypatch):
    """Шаблонная проверка без настроенного шаблона — техническая ошибка, как раньше."""
    monkeypatch.setattr(
        "app.services.validation.get_template_for_validation", lambda db, vid: None
    )
    doc_id = seed_document()
    report = run_validation(doc_id, checks=["template"])
    assert report.error_message == "Шаблон требований не настроен"
    with SessionLocal() as db:
        doc = db.get(ConfluenceDocument, doc_id)
        assert doc.validation_status == ValidationStatus.ERROR
        assert doc.last_validated_at is None


def test_ai_only_failed_ai_fails_document(client, fake_ai):
    doc_id = seed_document()
    FakeAIValidator.result = AIValidationResult(
        passed=False, summary="итог", findings_markdown="- ❌ пробел",
        findings_count=1, model="t",
    )
    report = run_validation(doc_id, checks=["ai"])
    assert report.template_passed is None
    assert report.ai_passed is False
    assert report.overall_passed is False
    with SessionLocal() as db:
        assert db.get(ConfluenceDocument, doc_id).validation_status == ValidationStatus.FAILED


def test_checks_idempotency_by_subset(client, fake_ai):
    """Кэш ФТ-CR-14 работает, только если запрошенные проверки в нём выполнены."""
    doc_id = seed_document()
    first = run_validation(doc_id, checks=["template"])
    second = run_validation(doc_id, checks=["template"])  # тот же набор — из кэша
    assert fake_ai.calls == 0
    assert second.id == first.id
    both = run_validation(doc_id)  # оба критерия — полный перезапуск
    assert fake_ai.calls == 1
    assert both.id != first.id
    assert both.template_passed is not None and both.ai_passed is not None


def test_prompt_ignored_when_ai_not_requested(client, fake_ai):
    doc_id = seed_document()
    first = run_validation(doc_id, checks=["template"], ai_prompt="особый промт")
    assert first.ai_prompt is None  # промт без ИИ-проверки не применяется
    second = run_validation(doc_id, checks=["template"], ai_prompt="другой промт")
    assert second.id == first.id  # и перевалидацию не форсирует


def test_validate_endpoint_passes_checks(client, monkeypatch):
    doc_id = seed_document()
    captured: dict = {}

    def fake_run(document_id, *, trigger, force=False, template_version_id=None, ai_prompt=None, checks=None, criterion_ids=None):
        captured["checks"] = checks
        return SimpleNamespace(id=9)

    monkeypatch.setattr(tasks, "run_validation", fake_run)
    assert client.post(f"/api/documents/{doc_id}/validate", json={"checks": ["ai"]}).status_code == 202
    for _ in range(50):
        state = tasks.validation_status().get(doc_id, {})
        if state.get("status") in {"done", "error", "not_found"}:
            break
        time.sleep(0.05)
    assert captured["checks"] == ["ai"]


def test_batch_passes_checks(client, monkeypatch):
    doc_id = seed_document()
    seen: list[list[str] | None] = []

    async def fake_exec(document_id, trigger, force, template_version_id=None, ai_prompt=None, checks=None, criterion_ids=None):
        seen.append(checks)
        return SimpleNamespace(id=document_id)

    monkeypatch.setattr(tasks, "_execute_validation", fake_exec)
    resp = client.post(
        "/api/documents/validate-batch",
        json={"document_ids": [doc_id], "checks": ["template"]},
    )
    assert resp.status_code == 202
    wait_bulk_done()
    assert seen == [["template"]]


def test_checks_validation_422(client):
    doc_id = seed_document()
    assert (
        client.post("/api/documents/validate-batch", json={"document_ids": [doc_id], "checks": []}).status_code
        == 422
    )
    assert (
        client.post("/api/documents/validate-batch", json={"document_ids": [doc_id], "checks": ["bogus"]}).status_code
        == 422
    )


def test_duplicate_checks_collapsed(client, monkeypatch):
    doc_id = seed_document()
    captured: dict = {}

    def fake_run(document_id, *, trigger, force=False, template_version_id=None, ai_prompt=None, checks=None, criterion_ids=None):
        captured["checks"] = checks
        return SimpleNamespace(id=9)

    monkeypatch.setattr(tasks, "run_validation", fake_run)
    assert (
        client.post(f"/api/documents/{doc_id}/validate", json={"checks": ["template", "template"]}).status_code
        == 202
    )
    for _ in range(50):
        state = tasks.validation_status().get(doc_id, {})
        if state.get("status") in {"done", "error", "not_found"}:
            break
        time.sleep(0.05)
    assert captured["checks"] == ["template"]  # дубликаты схлопнулись


def test_template_id_not_checked_when_template_unrequested(client, monkeypatch):
    """Шаблон не выбран — битый template_id не блокирует запуск проверки наполнения."""
    doc_id = seed_document()
    monkeypatch.setattr(
        tasks, "run_validation", lambda document_id, **kw: SimpleNamespace(id=1)
    )
    resp = client.post(f"/api/documents/{doc_id}/validate", json={"checks": ["ai"], "template_id": 999})
    assert resp.status_code == 202


def test_report_template_passed_is_null_for_ai_only(client, fake_ai):
    doc_id = seed_document()
    run_validation(doc_id, checks=["ai"])
    body = client.get(f"/api/documents/{doc_id}/report").json()
    assert body["template_passed"] is None
    assert body["ai_passed"] is True
