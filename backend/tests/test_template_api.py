"""Тесты API редактора шаблона: сид из файла, версии, валидация, интеграция."""

from __future__ import annotations

from app.database import SessionLocal
from app.models import Analyst, ConfluenceDocument
from app.services.ai_validator import AIValidationResult
from app.services.validation import run_validation
from app.utils import now_utc


def h(level: int, text: str) -> str:
    return f"<h{level}>{text}</h{level}>"


def put_payload(**overrides) -> dict:
    payload = {
        "title_marker": "СТ",
        "sections": [
            {"level": 1, "text": "Введение", "required": True, "aliases": []},
            {"level": 2, "text": "Общая информация", "required": True, "aliases": []},
        ],
    }
    payload.update(overrides)
    return payload


def test_get_template_seeds_from_file(client):
    resp = client.get("/api/template")
    assert resp.status_code == 200
    body = resp.json()
    assert body["title_marker"] == "СТ"  # из title_pattern "\[СТ\]"
    assert body["sections"][0] == {
        "level": 1,
        "text": "Введение",
        "required": True,
        "aliases": [],
    }
    # алиасы из файла сохраняются
    artifacts = next(s for s in body["sections"] if s["text"] == "Полезные артефакты")
    assert artifacts["aliases"] == ["Полезные ресурсы"]
    assert body["id"] == 1


def test_put_creates_new_active_version(client):
    resp = client.put("/api/template", json=put_payload(title_marker="GDS"))
    assert resp.status_code == 200
    assert resp.json()["title_marker"] == "GDS"

    # GET отдаёт новую версию, номер вырос
    body = client.get("/api/template").json()
    assert body["id"] == 2 and body["title_marker"] == "GDS"

    versions = client.get("/api/template/versions").json()
    assert [v["id"] for v in versions] == [2, 1]  # свежие сверху
    assert versions[0]["is_active"] is True and versions[1]["is_active"] is False
    assert versions[0]["section_count"] == 2


def test_put_normalizes_level_holes(client):
    resp = client.put(
        "/api/template",
        json=put_payload(
            sections=[
                {"level": 1, "text": "Введение", "required": True, "aliases": []},
                {"level": 3, "text": "Прыжок", "required": False, "aliases": []},
            ]
        ),
    )
    assert resp.status_code == 200
    body = client.get("/api/template").json()
    assert [s["level"] for s in body["sections"]] == [1, 2]


def test_put_rejects_duplicate_sibling_sections(client):
    resp = client.put(
        "/api/template",
        json=put_payload(
            sections=[
                {"level": 1, "text": "Введение", "required": True, "aliases": []},
                {"level": 2, "text": "Риски", "required": False, "aliases": []},
                {"level": 2, "text": "риски", "required": False, "aliases": []},
            ]
        ),
    )
    assert resp.status_code == 422
    assert "повторяется" in resp.json()["detail"]
    # активной осталась сид-версия
    assert client.get("/api/template").json()["id"] == 1


def test_put_rejects_invalid_payload(client):
    assert (
        client.put(
            "/api/template",
            json=put_payload(
                sections=[{"level": 4, "text": "Слишком глубоко", "required": False}]
            ),
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/template",
            json=put_payload(sections=[{"level": 1, "text": "   ", "required": False}]),
        ).status_code
        == 422
    )


def test_validation_uses_saved_template_and_keeps_repeatable_blocks(client, monkeypatch):
    """Проверка документа идёт по шаблону из БД: новый маркер применяется,
    повторяемые блоки доработок переносятся из сид-версии без изменений."""
    monkeypatch.setattr(
        "app.services.validation.AIValidator",
        lambda: type(
            "StubAI",
            (),
            {
                "validate": staticmethod(
                    lambda title, markdown, system_prompt=None: AIValidationResult(
                        passed=True,
                        summary="ok",
                        findings_markdown="✅ Замечаний нет.",
                        findings_count=0,
                        model="test",
                    )
                )
            },
        )(),
    )

    # Новый шаблон: маркер GDS, обязательные Введение и Функциональные требования
    assert (
        client.put(
            "/api/template",
            json=put_payload(
                title_marker="GDS",
                sections=[
                    {"level": 1, "text": "Введение", "required": True, "aliases": []},
                    {"level": 1, "text": "Функциональные требования", "required": True, "aliases": []},
                ],
            ),
        ).status_code
        == 200
    )

    body = "".join(
        [
            h(1, "Введение"),
            h(1, "Функциональные требования"),
            h(2, "Доработка первая"),
            h(3, "Общее описание"),
            # нет «Критериев приёмки» и «Документации по функционалу»
        ]
    )
    with SessionLocal() as db:
        analyst = Analyst(full_name="Тест", email="tpl@mts.ru")
        db.add(analyst)
        db.flush()
        doc = ConfluenceDocument(
            analyst_id=analyst.id,
            confluence_page_id=f"tpl-{now_utc().timestamp()}",
            title="1. [СТ] Доработка",  # старого маркера больше не хватает
            url="https://conf.test/pages/tpl",
            content_html=body,
            last_modified_in_confluence_at=now_utc(),
        )
        db.add(doc)
        db.commit()
        doc_id = doc.id

    report = run_validation(doc_id)
    assert not report.template_passed
    md = report.template_findings
    assert "маркер «GDS»" in md          # маркер из сохранённой версии
    assert "Критерии приёмки" in md      # блоки доработок перенесены из сида
    assert "Документация по функционалу" in md


def test_empty_marker_and_sections_allowed(client):
    """Шаблон из одного маркера (или без него) — легитимный минимум."""
    resp = client.put("/api/template", json={"title_marker": "СТ", "sections": []})
    assert resp.status_code == 200
    assert resp.json()["sections"] == []
