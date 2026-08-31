"""Справочник ИИ-критериев: сидинг, коды, сборка промта, CRUD с архивом
и интеграция с валидацией — выбор критериев на запуск, хэш промта в
идемпотентности (ФТ-CR-14), аудит «чем собирали промт» в отчёте.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

from app.database import Base, SessionLocal, engine
from app.models import Analyst, ConfluenceDocument, ValidationStatus
from app.services import tasks
from app.services.ai_settings import AIConnection
from app.clients.ai_validator import AIValidationResult
from app.services.criteria import (
    PROMPT_HEAD,
    assemble_prompt,
    seed_criteria_if_missing,
    select_criteria,
    slugify_code,
)
from app.services.validation import run_validation
from app.utils import now_utc

import pytest


@pytest.fixture(autouse=True)
def _db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def seed_document(title: str = "[СТ] Доработка") -> int:
    with SessionLocal() as db:
        analyst = Analyst(
            full_name="Тест", email=f"crit-{now_utc().timestamp()}-{id(object())}@mts.ru"
        )
        db.add(analyst)
        db.flush()
        doc = ConfluenceDocument(
            analyst_id=analyst.id,
            confluence_page_id=str(now_utc().timestamp()).replace(".", ""),
            title=title,
            url="https://conf.test/pages/crit",
            content_html="<h1>Введение</h1><h2>Общая информация</h2>",
            last_modified_in_confluence_at=now_utc(),
        )
        db.add(doc)
        db.commit()
        return doc.id


class FakeAIValidator:
    """Подмена ИИ: запоминает промт каждого вызова, результат можно подменять."""

    calls = 0
    prompts: list[str | None] = []

    def __init__(self, *args, **kwargs):
        pass  # продакшн-код передаёт connection= — фейку он не нужен

    def validate(self, title, markdown, system_prompt=None, expected_criteria=None):
        type(self).calls += 1
        type(self).prompts.append(system_prompt)
        return AIValidationResult(
            passed=True, summary="ok", findings_markdown="✅", findings_count=0, model="t"
        )


@pytest.fixture()
def fake_ai(monkeypatch):
    FakeAIValidator.calls = 0
    FakeAIValidator.prompts = []
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


def seeded_codes(client) -> list[str]:
    """Коды стартовых критериев (в порядке сида) — для ожиданий в тестах."""
    return [c["code"] for c in client.get("/api/ai-criteria").json() if not c["is_archived"]]


# --- код критерия и сидинг ---


def test_slugify_code_transliterates():
    assert slugify_code("Полнота описания") == "polnota_opisaniya"
    assert slugify_code("Однозначность формулировок") == "odnoznachnost_formulirovok"
    assert slugify_code("  Кибер-безопасность!! ") == "kiber_bezopasnost"
    assert slugify_code("API стиль") == "api_stil"
    assert slugify_code("!!!") == "criterion"  # название целиком из символов


def test_seed_creates_three_criteria_once(client):
    body = client.get("/api/ai-criteria").json()
    assert [c["code"] for c in body] == [
        "polnota_opisaniya",
        "neprotivorechivost_trebovanii",
        "odnoznachnost_formulirovok",
    ]
    assert all(not c["is_archived"] for c in body)
    # сид идемпотентен: повторный запрос не дублирует справочник
    assert len(client.get("/api/ai-criteria").json()) == 3


def test_assemble_prompt_head_blocks_tail(client):
    with SessionLocal() as db:
        seed_criteria_if_missing(db)
        criteria = select_criteria(db)
    prompt = assemble_prompt(criteria)
    assert prompt.startswith(PROMPT_HEAD)
    assert "1. «Полнота описания» — " in prompt
    assert "2. «Непротиворечивость требований» — " in prompt
    assert "3. «Однозначность формулировок» — " in prompt
    assert "Ответ строго в JSON" in prompt  # хвост с контрактом ответа


def test_prompt_tail_binds_findings_to_chosen_criteria(client):
    """Хвост промта не тащит легаси-представление о «правильных» критериях
    (эпоха зашитых полноты/непротиворечивости/однозначности): проверка идёт
    строго по выбранным критериям, вне-критериальные замечания запрещены —
    иначе ИИ сам расширяет проверку, даже когда выбран один специфичный
    критерий (например, «Соответствие шаблону»)."""
    with SessionLocal() as db:
        seed_criteria_if_missing(db)
        criteria = select_criteria(db, [1])  # один критерий — как узкий запуск
    prompt = assemble_prompt(criteria)
    # легаси-запрет «не соответствие шаблону» конфликтовал с пользовательским
    # критерием про шаблон и вынуждал модель вернуться к «содержимому»
    assert "не соответствие шаблону" not in prompt
    assert "строго по перечисленным выше критериям" in prompt
    # «|другое» в контракте приглашало модель к вне-критериальным находкам
    assert "название одного из перечисленных критериев" in prompt
    assert "|другое" not in prompt


# --- CRUD справочника: создать / править / архив / восстановить ---


def test_criterion_crud_archive_restore(client):
    created = client.post(
        "/api/ai-criteria",
        json={
            "name": "Трассировка требований",
            "prompt": "каждое требование связано с целью доработки и проверяется по критерию приёмки.",
        },
    )
    assert created.status_code == 201
    crit = created.json()
    assert crit["code"] == "trassirovka_trebovanii"  # код из названия
    assert not crit["is_archived"]

    # правка: название и промт меняются, код стабилен
    updated = client.put(
        f"/api/ai-criteria/{crit['id']}",
        json={"name": "Трассировка на цели", "prompt": "обновлённый промт критерия, подлиннее."},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Трассировка на цели"
    assert updated.json()["code"] == "trassirovka_trebovanii"

    # удаление = архив: критерий остаётся в справочнике, но уходит в конец
    archived = client.delete(f"/api/ai-criteria/{crit['id']}")
    assert archived.status_code == 200
    assert archived.json()["is_archived"] is True
    body = client.get("/api/ai-criteria").json()
    assert body[-1]["id"] == crit["id"]

    # повторное удаление идемпотентно
    assert client.delete(f"/api/ai-criteria/{crit['id']}").json()["is_archived"] is True

    restored = client.post(f"/api/ai-criteria/{crit['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["is_archived"] is False


def test_duplicate_name_gets_suffixed_code(client):
    payload = {"name": "Аудит разделов", "prompt": "промт про аудит разделов документа, достаточно длинный."}
    first = client.post("/api/ai-criteria", json=payload).json()
    second = client.post("/api/ai-criteria", json=payload).json()
    assert first["code"] == "audit_razdelov"
    assert second["code"] == "audit_razdelov_2"  # код уникален, название может повторяться


def test_criterion_validation_422(client):
    # название из пробелов / слишком короткий промт
    assert (
        client.post(
            "/api/ai-criteria", json={"name": "   ", "prompt": "достаточно длинный промт критерия."}
        ).status_code
        == 422
    )
    assert (
        client.post("/api/ai-criteria", json={"name": "Имя", "prompt": "коротко"}).status_code == 422
    )


def test_criterion_unknown_404(client):
    payload = {"name": "Имя", "prompt": "достаточно длинный промт критерия."}
    assert client.put("/api/ai-criteria/999", json=payload).status_code == 404
    assert client.delete("/api/ai-criteria/999").status_code == 404
    assert client.post("/api/ai-criteria/999/restore").status_code == 404


# --- конфиг диалога проверки ---


def test_validation_config_exposes_criteria_and_prompt_parts(client):
    body = client.get("/api/validation-config").json()
    assert "polnota_opisaniya" in [c["code"] for c in body["criteria"]]
    assert body["prompt_head"].startswith("Ты — опытный")
    assert "Ответ строго в JSON" in body["prompt_tail"]
    assert body["default_prompt"]  # легаси-поле остаётся для старых клиентов


def test_validation_config_hides_archived(client):
    crit = client.post(
        "/api/ai-criteria",
        json={"name": "Скрытый критерий", "prompt": "промт скрываемого критерия, достаточно длинный."},
    ).json()
    client.delete(f"/api/ai-criteria/{crit['id']}")
    body = client.get("/api/validation-config").json()
    assert crit["id"] not in [c["id"] for c in body["criteria"]]


# --- валидация: сборка промта из критериев ---


def test_first_run_assembles_prompt_from_criteria(client, fake_ai):
    doc_id = seed_document()
    report = run_validation(doc_id)
    prompt = fake_ai.prompts[0]
    assert prompt.startswith(PROMPT_HEAD)
    assert "1. «Полнота описания» — " in prompt
    assert "3. «Однозначность формулировок» — " in prompt
    # аудит: чем собирали промт прогона и его хэш
    assert json.loads(report.ai_criteria_codes) == [
        "polnota_opisaniya",
        "neprotivorechivost_trebovanii",
        "odnoznachnost_formulirovok",
    ]
    assert report.ai_prompt_hash
    assert report.ai_prompt is None  # собранный — не override, в отчёт не пишем


def test_same_criteria_cached_prompt_edit_revalidates(client, fake_ai):
    """ФТ-CR-14 по новому промту: тот же набор критериев — кэш; правка промта
    критерия меняет собранный промт → перевалидация без force."""
    doc_id = seed_document()
    first = run_validation(doc_id)
    second = run_validation(doc_id)  # тот же набор — идемпотентность
    assert fake_ai.calls == 1
    assert second.id == first.id

    crit = client.get("/api/ai-criteria").json()[0]
    client.put(
        f"/api/ai-criteria/{crit['id']}",
        json={"name": crit["name"], "prompt": crit["prompt"] + " Особое внимание к граничным случаям."},
    )
    third = run_validation(doc_id)
    assert fake_ai.calls == 2  # хэш собранного промта изменился
    assert third.id != first.id


def test_selected_criteria_keep_order_and_dedupe(client, fake_ai):
    doc_id = seed_document()
    ids = [c["id"] for c in client.get("/api/ai-criteria").json()]
    report = run_validation(doc_id, criterion_ids=[ids[2], ids[0], ids[2]])
    prompt = fake_ai.prompts[0]
    # порядок передачи сохранён, дубль схлопнут, невыбранный не попал
    assert "1. «Однозначность формулировок» — " in prompt
    assert "2. «Полнота описания» — " in prompt
    assert "Непротиворечивость" not in prompt
    assert json.loads(report.ai_criteria_codes) == [
        "odnoznachnost_formulirovok",
        "polnota_opisaniya",
    ]


def test_narrower_criteria_set_revalidates(client, fake_ai):
    """Другой набор критериев = другой собранный промт → кэш не срабатывает."""
    doc_id = seed_document()
    run_validation(doc_id)  # все три
    first_id = json.loads(run_validation(doc_id).ai_criteria_codes)  # кэш, без вызова ИИ
    assert fake_ai.calls == 1

    ids = [c["id"] for c in client.get("/api/ai-criteria").json()]
    report = run_validation(doc_id, criterion_ids=[ids[0]])
    assert fake_ai.calls == 2
    assert json.loads(report.ai_criteria_codes) == ["polnota_opisaniya"]
    assert first_id  # предыдущий отчёт отдавал все три кода


def test_override_prompt_with_selected_criteria(client, fake_ai):
    doc_id = seed_document()
    ids = [c["id"] for c in client.get("/api/ai-criteria").json()]
    report = run_validation(
        doc_id, ai_prompt="особый промт этой проверки", criterion_ids=[ids[0]]
    )
    assert fake_ai.prompts == ["особый промт этой проверки"]
    assert report.ai_prompt == "особый промт этой проверки"
    # чем собирали запуск, видно и при override (сняли замок поверх выбора)
    assert json.loads(report.ai_criteria_codes) == ["polnota_opisaniya"]


def test_no_active_criteria_error_report(client, fake_ai):
    doc_id = seed_document()
    for crit in client.get("/api/ai-criteria").json():
        client.delete(f"/api/ai-criteria/{crit['id']}")
    report = run_validation(doc_id)
    assert report.error_message == "Нет активных ИИ-критериев — добавьте или восстановите"
    assert fake_ai.calls == 0
    with SessionLocal() as db:
        assert db.get(ConfluenceDocument, doc_id).validation_status == ValidationStatus.ERROR


# --- API запуска: criterion_ids ---


def test_validate_endpoint_passes_criterion_ids(client, monkeypatch):
    doc_id = seed_document()
    captured: dict = {}

    def fake_run(document_id, *, trigger, force=False, template_version_id=None, ai_prompt=None, checks=None, criterion_ids=None):
        captured["criterion_ids"] = criterion_ids
        return SimpleNamespace(id=9)

    monkeypatch.setattr(tasks, "run_validation", fake_run)
    ids = [c["id"] for c in client.get("/api/ai-criteria").json()]
    resp = client.post(
        f"/api/documents/{doc_id}/validate",
        json={"checks": ["ai"], "criterion_ids": [ids[0]]},
    )
    assert resp.status_code == 202
    for _ in range(50):
        state = tasks.validation_status().get(doc_id, {})
        if state.get("status") in {"done", "error", "not_found"}:
            break
        time.sleep(0.05)
    assert captured["criterion_ids"] == [ids[0]]


def test_criterion_ids_empty_422(client):
    doc_id = seed_document()
    resp = client.post(
        f"/api/documents/{doc_id}/validate", json={"checks": ["ai"], "criterion_ids": []}
    )
    assert resp.status_code == 422


def test_criterion_unknown_or_archived_404(client):
    doc_id = seed_document()
    resp = client.post(
        f"/api/documents/{doc_id}/validate", json={"checks": ["ai"], "criterion_ids": [999]}
    )
    assert resp.status_code == 404
    assert "не найден" in resp.json()["detail"]

    crit = client.post(
        "/api/ai-criteria",
        json={"name": "Архивный критерий", "prompt": "промт архивируемого критерия, достаточно длинный."},
    ).json()
    client.delete(f"/api/ai-criteria/{crit['id']}")
    resp = client.post(
        f"/api/documents/{doc_id}/validate", json={"checks": ["ai"], "criterion_ids": [crit["id"]]}
    )
    assert resp.status_code == 404
    assert "архиве" in resp.json()["detail"]


def test_criterion_ids_not_checked_without_ai(client, monkeypatch):
    """ИИ-проверка не выбрана — битые criterion_ids не блокируют запуск шаблона."""
    doc_id = seed_document()
    monkeypatch.setattr(
        tasks, "run_validation", lambda document_id, **kw: SimpleNamespace(id=1)
    )
    resp = client.post(
        f"/api/documents/{doc_id}/validate",
        json={"checks": ["template"], "criterion_ids": [999]},
    )
    assert resp.status_code == 202


def test_batch_passes_criterion_ids(client, monkeypatch):
    doc_id = seed_document()
    seen: list[list[int] | None] = []

    async def fake_exec(document_id, trigger, force, template_version_id=None, ai_prompt=None, checks=None, criterion_ids=None):
        seen.append(criterion_ids)
        return SimpleNamespace(id=document_id)

    monkeypatch.setattr(tasks, "_execute_validation", fake_exec)
    ids = [c["id"] for c in client.get("/api/ai-criteria").json()]
    resp = client.post(
        "/api/documents/validate-batch",
        json={"document_ids": [doc_id], "criterion_ids": [ids[0]]},
    )
    assert resp.status_code == 202
    deadline = time.monotonic() + 5.0
    while tasks.bulk_status()["running"] and time.monotonic() < deadline:
        time.sleep(0.05)
    assert seen == [[ids[0]]]
