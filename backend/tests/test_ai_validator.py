"""Тесты ИИ-валидации через GLM (ФТ-CR-11) — фейковый клиент, без сети."""

from __future__ import annotations

import httpx
import pytest
from types import SimpleNamespace

import anthropic

from app.config import Settings
from app.services.ai_validator import (
    AIValidationError,
    AIValidator,
    _extract_json,
)

PASSED_JSON = '{"passed": true, "summary": "Документ в порядке.", "findings": []}'

FAILED_JSON = """
{
  "passed": false,
  "summary": "Требования неполные.",
  "findings": [
    {
      "criterion": "полнота",
      "severity": "critical",
      "message": "В разделе «Критерии приёмки» не описана обработка ошибок."
    },
    {
      "criterion": "однозначность",
      "severity": "minor",
      "message": "Формулировка «быстро» в разделе «Производительность» неизмерима."
    }
  ]
}
"""


def make_validator(payload: str) -> tuple[AIValidator, list[dict]]:
    """Валидатор с фейковым клиентом; calls накапливает kwargs запросов."""
    calls: list[dict] = []

    class FakeMessages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text=payload)],
                stop_reason="end_turn",
                model="glm-4.5",
            )

    settings = Settings(ai_api_key="test-key", ai_model="glm-4.5-test", _env_file=None)
    validator = AIValidator(client=SimpleNamespace(messages=FakeMessages()), settings=settings)
    return validator, calls


def test_passed_document():
    validator, calls = make_validator(PASSED_JSON)
    result = validator.validate("[СТ] Документ", "# Введение\nТекст")
    assert result.passed
    assert result.findings_count == 0
    assert "✅" in result.findings_markdown
    assert result.model == "glm-4.5"
    assert result.summary == "Документ в порядке."


def test_request_shape():
    validator, calls = make_validator(PASSED_JSON)
    validator.validate("[СТ] Документ", "# Введение")
    assert len(calls) == 1
    kwargs = calls[0]
    assert kwargs["model"] == "glm-4.5-test"
    assert kwargs["max_tokens"] == 4000
    assert "системный аналитик" in kwargs["system"]
    assert "[СТ] Документ" in kwargs["messages"][0]["content"]


def test_failed_document_with_findings():
    validator, _ = make_validator(FAILED_JSON)
    result = validator.validate("[СТ] Документ", "текст")
    assert not result.passed
    assert result.findings_count == 2
    md = result.findings_markdown
    assert "[полнота, critical]" in md
    assert "обработка ошибок" in md
    assert "[однозначность, minor]" in md


def test_critical_finding_overrides_models_passed():
    payload = PASSED_JSON.replace('"findings": []', """
    "findings": [{"criterion": "непротиворечивость", "severity": "critical",
                  "message": "Противоречие форматов."}]""")
    validator, _ = make_validator(payload)
    result = validator.validate("[СТ] Документ", "текст")
    assert not result.passed  # модель сказала passed, но critical = провал


def test_json_inside_code_fence():
    validator, _ = make_validator(f"Вот оценка:\n```json\n{PASSED_JSON}\n```")
    result = validator.validate("[СТ] Документ", "текст")
    assert result.passed


def test_garbage_response_raises():
    validator, _ = make_validator("Модель сломалась и отвечает текстом без JSON")
    with pytest.raises(AIValidationError, match="JSON"):
        validator.validate("[СТ] Документ", "текст")


def test_empty_response_raises():
    validator, _ = make_validator("   ")
    with pytest.raises(AIValidationError, match="пустой"):
        validator.validate("[СТ] Документ", "текст")


def test_connection_error_wrapped():
    calls: list[dict] = []

    class FakeMessages:
        def create(self, **kwargs):
            calls.append(kwargs)
            raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://z.ai"))

    settings = Settings(ai_api_key="k", _env_file=None)
    validator = AIValidator(client=SimpleNamespace(messages=FakeMessages()), settings=settings)
    with pytest.raises(AIValidationError, match="связи"):
        validator.validate("[СТ] Документ", "текст")


def test_extract_json_variants():
    assert _extract_json('{"a": 1}') == {"a": 1}
    assert _extract_json('Ответ: {"a": {"b": 2}} конец') == {"a": {"b": 2}}
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ValueError):
        _extract_json("совсем не JSON")
