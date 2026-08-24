"""ИИ-валидация содержимого документа требований через GLM (ФТ-CR-11).

Подключение настраивается глобально (env + таблица ai_connection_settings,
см. services.ai_settings): Anthropic-совместимый API (по умолчанию z.ai)
или OpenAI-совместимый (POST {base_url}/chat/completions). Оценка идёт по
трём критериям качества: полнота, непротиворечивость, однозначность для
разработчика.

passed вычисляется дважды: модель даёт свою оценку, но любое замечание
серьёзности critical гарантированно проваливает проверку — защита от
противоречивых ответов модели.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

import anthropic
import httpx

from app.config import Settings, get_settings
from app.services.ai_settings import AIConnection, connection_from_settings

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

# Паузы между попытками POST (429/5xx). В тестах патчатся на нули.
_RETRY_DELAYS: tuple[float, ...] = (0.5, 1.0)


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


def _openai_error_message(response: httpx.Response) -> str:
    """HTTP-статус OpenAI-совместимого API → русское сообщение.

    В текст ошибки не попадают ключ и заголовки — только статус и короткий
    выдержка тела провайдера.
    """
    status = response.status_code
    if status == 401:
        return "Неверный API-ключ ИИ (401)"
    if status == 403:
        return "API-ключ ИИ не имеет доступа к модели (403)"
    if status == 404:
        return "Модель или эндпоинт ИИ не найден (404)"
    if status == 429:
        return "Превышен лимит запросов к ИИ (429)"
    if status == 400:
        excerpt = " ".join(response.text.split())[:200]
        return f"ИИ отклонил запрос (400): {excerpt}"
    return f"Ошибка ИИ (HTTP {status})"


def _join_openai_content(content) -> str:
    """content у OpenAI-совместимых API — строка, список частей или None.

    None бывает у reasoning-моделей: бюджет токенов съеден рассуждением,
    текста нет — это «пустой ответ», а не ошибка транспорта.
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ).strip()
    return ""


class AIValidator:
    """Обёртка над Anthropic- или OpenAI-совместимым API.

    client (anthropic) и http_client (httpx) передаются в тестах; в проде
    создаются лениво из эффективного подключения, чтобы импорт модуля
    не требовал AI_API_KEY.
    """

    def __init__(
        self,
        client=None,
        settings: Settings | None = None,
        connection: AIConnection | None = None,
        http_client: httpx.Client | None = None,
    ):
        self._conn = connection or connection_from_settings(settings or get_settings())
        self._client = client
        self._http = http_client

    def _get_client(self):
        if self._client is None:
            self._client = anthropic.Anthropic(
                api_key=self._conn.api_key,
                base_url=self._conn.base_url,
                timeout=self._conn.timeout_seconds,
                max_retries=2,
            )
        return self._client

    def _get_http(self) -> httpx.Client:
        if self._http is None:
            # connect-таймаут меньше общего: кнопка «Проверить подключение»
            # должна быстро падать на недоступном хосте
            self._http = httpx.Client(
                timeout=httpx.Timeout(self._conn.timeout_seconds, connect=10.0)
            )
        return self._http

    def ping(self) -> str:
        """Минимальный живой запрос — «Проверить подключение» в настройках."""
        text, model = self._complete(
            "Проверка подключения к ИИ.", "Ответь одним словом: ok", max_tokens=8
        )
        if text:
            return f"Модель {model} ответила"
        return f"Подключение установлено (модель {model} ответила пусто)"

    def validate(
        self, title: str, markdown: str, system_prompt: str | None = None
    ) -> AIValidationResult:
        """Оценить документ (заголовок + содержимое в Markdown).

        system_prompt — переопределение стандартного промта на один запуск
        (выбор пользователя в диалоге проверки); None — стандартный.
        """
        user_message = f"Документ требований «{title}»:\n\n{markdown}"
        text, model = self._complete(system_prompt or SYSTEM_PROMPT, user_message)
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
            model=model,
        )

    def _complete(self, system: str, user: str, max_tokens: int | None = None) -> tuple[str, str]:
        """Один запрос к ИИ в формате выбранного протокола → (текст, модель)."""
        limit = max_tokens or self._conn.max_tokens
        if self._conn.protocol == "openai":
            return self._request_openai(system, user, limit)
        return self._request_anthropic(system, user, limit)

    def _request_anthropic(self, system: str, user: str, max_tokens: int) -> tuple[str, str]:
        try:
            response = self._get_client().messages.create(
                model=self._conn.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.AuthenticationError as exc:
            raise AIValidationError("Неверный API-ключ ИИ (401)") from exc
        except anthropic.PermissionDeniedError as exc:
            raise AIValidationError("API-ключ ИИ не имеет доступа к модели (403)") from exc
        except anthropic.NotFoundError as exc:
            raise AIValidationError(
                f"Модель или эндпоинт ИИ не найден (404): {self._conn.model}"
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
        return text, str(getattr(response, "model", "") or self._conn.model)

    def _request_openai(self, system: str, user: str, max_tokens: int) -> tuple[str, str]:
        url = f"{self._conn.base_url.rstrip('/')}/chat/completions"
        payload: dict = {
            "model": self._conn.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self._conn.api_key:
            headers["Authorization"] = f"Bearer {self._conn.api_key}"

        try:
            response = self._post_chat_completions(url, payload, headers)
            # у части reasoning-моделей поле переименовано — одна повторная
            # попытка с правильным именем
            if response.status_code == 400 and "max_completion_tokens" in response.text:
                payload["max_completion_tokens"] = payload.pop("max_tokens")
                response = self._post_chat_completions(url, payload, headers)
        except httpx.TimeoutException as exc:
            raise AIValidationError(
                f"Превышено время ожидания ИИ ({self._conn.timeout_seconds:.0f} с)"
            ) from exc
        except httpx.TransportError as exc:
            raise AIValidationError(f"Нет связи с ИИ: {exc}") from exc

        if response.status_code != 200:
            raise AIValidationError(_openai_error_message(response))

        try:
            data = response.json()
            message = ((data.get("choices") or [{}])[0].get("message")) or {}
        except ValueError as exc:
            raise AIValidationError(f"Не удалось разобрать ответ ИИ как JSON: {exc}") from exc
        text = _join_openai_content(message.get("content"))
        return text, str(data.get("model") or self._conn.model)

    def _post_chat_completions(
        self, url: str, payload: dict, headers: dict[str, str]
    ) -> httpx.Response:
        """POST /chat/completions с ретраями 429/5xx; транспортный сбой — сразу наружу."""
        response: httpx.Response | None = None
        delays = (0.0, *_RETRY_DELAYS)
        for delay in delays:
            if delay:
                time.sleep(delay)
            response = self._get_http().post(url, json=payload, headers=headers)
            if response.status_code != 429 and response.status_code < 500:
                return response
        return response  # type: ignore[return-value]
