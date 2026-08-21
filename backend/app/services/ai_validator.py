"""ИИ-валидация содержимого документа требований через GLM (ФТ-CR-11).

Модель доступна через Anthropic-совместимый API (по умолчанию z.ai,
настраивается AI_BASE_URL / AI_MODEL). Оценка идёт по трём критериям
качества: полнота, непротиворечивость, однозначность для разработчика.

passed вычисляется дважды: модель даёт свою оценку, но любое замечание
серьёзности critical гарантированно проваливает проверку — защита от
противоречивых ответов модели.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import anthropic

from app.config import Settings, get_settings

CRITERIA = ("полнота", "непротиворечивость", "однозначность")
SEVERITIES = ("critical", "major", "minor")

SYSTEM_PROMPT = f"""Ты — опытный ведущий системный аналитик, ревьюер технических требований.

Тебе дают документ требований (в Markdown), созданный аналитиком в Confluence.
Оцени качество содержимого по трём критериям:

1. «{CRITERIA[0]}» — описаны ли все сценарии использования доработки, граничные и
   ошибочные ситуации, предусловия и постусловия. Разработчику не должно
   понадобиться что-то додумывать.
2. «{CRITERIA[1]}» — нет ли противоречий между разделами документа
   (разные форматы данных, несовместимые правила, конфликтующие сценарии).
3. «{CRITERIA[2]}» — сможет ли разработчик реализовать требования без
   дополнительных уточнений: нет ли расплывчатых формулировок
   («по необходимости», «должно работать быстро»), неопределённых терминов,
   требований без критериев проверки.

Правила:
- Оценивай только содержимое, а не оформление и не соответствие шаблону —
  структуру проверяет отдельный скрипт.
- Ссылайся на раздел документа, к которому относится замечание.
- Не выдумывай проблем: замечание только если из текста это действительно следует.
- minor — стилистические шероховатости; major — существенный пробел или риск;
  critical — документ невозможно реализовать или требования противоречат друг другу.

Ответ строго в JSON без markdown-обёртки:
{{
  "passed": true|false,
  "summary": "краткое заключение в 1-3 предложениях",
  "findings": [
    {{
      "criterion": "{'|'.join(CRITERIA)}|другое",
      "severity": "{'|'.join(SEVERITIES)}",
      "message": "конкретное замечание с указанием раздела"
    }}
  ]
}}
Если замечаний нет — "passed": true и пустой список findings."""


class AIValidationError(Exception):
    """Технический сбой ИИ-валидации (сеть, ключ, неразборчивый ответ)."""


@dataclass(slots=True)
class AIFinding:
    criterion: str
    severity: str
    message: str


@dataclass(slots=True)
class AIValidationResult:
    passed: bool
    summary: str
    findings_markdown: str
    findings_count: int
    model: str


def _extract_json(text: str) -> dict:
    """JSON из ответа модели: как есть, либо вырезанный из ```json … ``` / текста."""
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("в ответе нет JSON-объекта")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("JSON не является объектом")
    return data


def _parse_findings(raw) -> list[AIFinding]:
    findings: list[AIFinding] = []
    if not isinstance(raw, list):
        return findings
    for item in raw:
        if not isinstance(item, dict):
            continue
        message = str(item.get("message") or "").strip()
        if not message:
            continue
        criterion = str(item.get("criterion") or "другое").strip().lower()
        if criterion not in CRITERIA:
            criterion = "другое"
        severity = str(item.get("severity") or "minor").strip().lower()
        if severity not in SEVERITIES:
            severity = "minor"
        findings.append(AIFinding(criterion=criterion, severity=severity, message=message))
    return findings


def _render_markdown(summary: str, findings: list[AIFinding]) -> str:
    lines: list[str] = []
    if summary:
        lines.append(summary)
        lines.append("")
    if not findings:
        lines.append("✅ Замечаний к содержимому нет.")
    else:
        for finding in findings:
            icon = {"critical": "❌", "major": "⚠️", "minor": "ℹ️"}[finding.severity]
            lines.append(f"- {icon} **[{finding.criterion}, {finding.severity}]** {finding.message}")
    return "\n".join(lines)


class AIValidator:
    """Обёртка над Anthropic-совместимым API с GLM-моделью.

    client передаётся в тестах; в проде создаётся лениво из настроек,
    чтобы импорт модуля не требовал AI_API_KEY.
    """

    def __init__(self, client=None, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._client = client

    def _get_client(self):
        if self._client is None:
            self._client = anthropic.Anthropic(
                api_key=self._settings.ai_api_key,
                base_url=self._settings.ai_base_url,
                timeout=self._settings.ai_timeout_seconds,
                max_retries=2,
            )
        return self._client

    def validate(self, title: str, markdown: str) -> AIValidationResult:
        """Оценить документ (заголовок + содержимое в Markdown)."""
        user_message = f"Документ требований «{title}»:\n\n{markdown}"
        try:
            response = self._get_client().messages.create(
                model=self._settings.ai_model,
                max_tokens=self._settings.ai_max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
        except anthropic.AuthenticationError as exc:
            raise AIValidationError("Неверный API-ключ ИИ (401)") from exc
        except anthropic.PermissionDeniedError as exc:
            raise AIValidationError("API-ключ ИИ не имеет доступа к модели (403)") from exc
        except anthropic.NotFoundError as exc:
            raise AIValidationError(
                f"Модель или эндпоинт ИИ не найден (404): {self._settings.ai_model}"
            ) from exc
        except anthropic.RateLimitError as exc:
            raise AIValidationError("Превышен лимит запросов к ИИ (429)") from exc
        except anthropic.BadRequestError as exc:
            raise AIValidationError(f"ИИ отклонил запрос (400): {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise AIValidationError(f"Ошибка ИИ (HTTP {exc.status_code})") from exc
        except anthropic.APIConnectionError as exc:
            raise AIValidationError(f"Нет связи с ИИ: {exc}") from exc
        except anthropic.APIError as exc:
            raise AIValidationError(f"Ошибка ИИ: {exc}") from exc

        text = "".join(
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        ).strip()
        if not text:
            raise AIValidationError("ИИ вернул пустой ответ")

        try:
            data = _extract_json(text)
        except (ValueError, json.JSONDecodeError) as exc:
            raise AIValidationError(f"Не удалось разобрать ответ ИИ как JSON: {exc}") from exc

        findings = _parse_findings(data.get("findings"))
        summary = str(data.get("summary") or "").strip()
        # критичное замечание проваливает проверку, даже если модель сказала passed
        passed = bool(data.get("passed")) and not any(f.severity == "critical" for f in findings)

        return AIValidationResult(
            passed=passed,
            summary=summary,
            findings_markdown=_render_markdown(summary, findings),
            findings_count=len(findings),
            model=str(getattr(response, "model", "") or self._settings.ai_model),
        )
