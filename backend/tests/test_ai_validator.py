"""Тесты ИИ-валидации (ФТ-CR-11) — фейковые клиенты, без сети.

Anthropic-совместимый протокол проверяется через подмену клиента,
OpenAI-совместимый — через httpx.MockTransport.
"""

from __future__ import annotations

import json

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


# --- канонизация ярлыка критерия по списку прогона ---


def test_finding_criterion_canonicalized_to_run_criteria():
    """Контракт промта («criterion» — название критерия прогона) — просьба,
    не гарантия: ярлык модели сверяется с критериями прогона без учёта
    регистра и заменяется каноническим названием из справочника."""
    payload = PASSED_JSON.replace(
        '"findings": []',
        '"findings": [{"criterion": "ПОЛНОТА ОПИСАНИЯ", "severity": "minor", '
        '"message": "Не описаны граничные случаи."}]',
    )
    validator, _ = make_validator(payload)
    result = validator.validate(
        "[СТ] Документ",
        "текст",
        expected_criteria=["Полнота описания", "Соответствие шаблону"],
    )
    assert "[Полнота описания, minor]" in result.findings_markdown


def test_finding_with_foreign_criterion_marked_outside():
    """Вне-критериальная находка не теряется, но помечается честно —
    она не относится ни к одному критерию прогона."""
    payload = PASSED_JSON.replace(
        '"findings": []',
        '"findings": [{"criterion": "Юзабилити интерфейса", "severity": "major", '
        '"message": "Замечание вне критериев прогона."}]',
    )
    validator, _ = make_validator(payload)
    result = validator.validate(
        "[СТ] Документ", "текст", expected_criteria=["Полнота описания"]
    )
    assert "[вне критериев, major]" in result.findings_markdown


def test_finding_criterion_without_expected_list_verbatim():
    """Легаси-вызов без списка критериев: ярлык модели проходит как есть."""
    payload = PASSED_JSON.replace(
        '"findings": []',
        '"findings": [{"criterion": "Соответствие шаблону", "severity": "minor", '
        '"message": "Раздел «Роли» вне шаблона."}]',
    )
    validator, _ = make_validator(payload)
    result = validator.validate("[СТ] Документ", "текст")
    assert "[Соответствие шаблону, minor]" in result.findings_markdown


def test_finding_empty_criterion_marked_outside():
    payload = PASSED_JSON.replace(
        '"findings": []',
        '"findings": [{"criterion": "", "severity": "minor", "message": "Без ярлыка."}]',
    )
    validator, _ = make_validator(payload)
    result = validator.validate("[СТ] Документ", "текст")
    assert "[вне критериев, minor]" in result.findings_markdown


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


# --- ping («Проверить подключение») ---


def test_ping_anthropic():
    validator, calls = make_validator("ok")
    assert validator.ping() == "Модель glm-4.5 ответила"
    assert calls[0]["max_tokens"] == 8  # мини-запрос, не полный прогон


# --- OpenAI-совместимый протокол (httpx.MockTransport, без сети) ---


def make_openai_validator(handler) -> tuple[AIValidator, list[httpx.Request]]:
    """Валидатор с httpx-транспортом; requests накапливает отправленное."""
    requests: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    settings = Settings(
        ai_protocol="openai",
        ai_base_url="https://ai.test/v1",
        ai_api_key="sk-test",
        ai_model="qwen2.5:7b",
        _env_file=None,
    )
    http = httpx.Client(transport=httpx.MockTransport(transport))
    return AIValidator(settings=settings, http_client=http), requests


def ok_response(content, model="qwen2.5:7b") -> httpx.Response:
    return httpx.Response(
        200,
        json={"model": model, "choices": [{"message": {"role": "assistant", "content": content}}]},
    )


def test_openai_request_shape():
    validator, requests = make_openai_validator(lambda request: ok_response(PASSED_JSON))
    result = validator.validate("[СТ] Документ", "# Введение")
    assert result.passed
    assert result.model == "qwen2.5:7b"

    request = requests[0]
    assert str(request.url) == "https://ai.test/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer sk-test"
    body = json.loads(request.content)
    assert body["model"] == "qwen2.5:7b"
    assert body["max_tokens"] == 4000
    assert body["messages"][0]["role"] == "system"
    assert "системный аналитик" in body["messages"][0]["content"]
    assert "[СТ] Документ" in body["messages"][1]["content"]


def test_openai_content_as_parts():
    # часть провайдеров отдаёт content списком частей (reasoning-блоки мешаем)
    parts = [
        {"type": "text", "text": '{"passed": '},
        {"type": "reasoning", "text": "размышления"},
        {"type": "text", "text": 'true, "summary": "ок", "findings": []}'},
    ]
    validator, _ = make_openai_validator(lambda request: ok_response(parts))
    assert validator.validate("[СТ] Документ", "текст").passed


@pytest.mark.parametrize("status,expected", [
    (401, "Неверный API-ключ ИИ \\(401\\)"),
    (403, "не имеет доступа"),
    (404, "не найден"),
    (429, "лимит запросов"),
    (500, "Ошибка ИИ \\(HTTP 500\\)"),
])
def test_openai_error_mapping(monkeypatch, status, expected):
    monkeypatch.setattr("app.services.ai_validator._RETRY_DELAYS", ())  # без пауз
    validator, _ = make_openai_validator(
        lambda request, status=status: httpx.Response(
            status, json={"error": {"message": "boom"}}
        )
    )
    with pytest.raises(AIValidationError, match=expected):
        validator.validate("[СТ] Документ", "текст")


def test_openai_bad_request_shows_excerpt(monkeypatch):
    monkeypatch.setattr("app.services.ai_validator._RETRY_DELAYS", ())
    validator, _ = make_openai_validator(
        lambda request: httpx.Response(400, json={"error": {"message": "Unknown model"}})
    )
    with pytest.raises(AIValidationError, match=r"400.*Unknown model"):
        validator.validate("[СТ] Документ", "текст")


def test_openai_retry_with_max_completion_tokens():
    calls: list[int] = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(
                400,
                json={"error": {"message": "Use 'max_completion_tokens' instead of 'max_tokens'"}},
            )
        return ok_response(PASSED_JSON)

    validator, _ = make_openai_validator(handler)
    assert validator.validate("[СТ] Документ", "текст").passed
    assert len(calls) == 2  # одна повторная попытка с переименованным полем


def test_openai_timeout_and_connect_error():
    def raise_timeout(request):
        raise httpx.ConnectTimeout("too slow")

    validator, _ = make_openai_validator(raise_timeout)
    with pytest.raises(AIValidationError, match="время ожидания"):
        validator.validate("[СТ] Документ", "текст")

    def raise_connect(request):
        raise httpx.ConnectError("no route")

    validator, _ = make_openai_validator(raise_connect)
    with pytest.raises(AIValidationError, match="связи"):
        validator.validate("[СТ] Документ", "текст")


def test_openai_empty_content_raises():
    # reasoning-модель съела бюджет токенов — текста нет
    validator, _ = make_openai_validator(lambda request: ok_response(None))
    with pytest.raises(AIValidationError, match="пустой"):
        validator.validate("[СТ] Документ", "текст")


def test_ping_openai():
    bodies: list[dict] = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return ok_response("ok")

    validator, _ = make_openai_validator(handler)
    assert validator.ping() == "Модель qwen2.5:7b ответила"
    assert bodies[0]["max_tokens"] == 8
