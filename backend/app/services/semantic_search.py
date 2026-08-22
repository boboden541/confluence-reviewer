"""Семантический поиск документов через GLM.

У ключа z.ai нет embedding-моделей (только чат-модели), поэтому поиск
устроен без векторов: одним дешёвым вызовом модель ранжирует заголовки
документов аналитика по смысловому соответствию запросу — синонимы и
родственные понятия находятся без совпадения слов.

Ответ кэшируется на 10 минут: возврат «Назад» или повтор запроса
не должен снова платить за вызов ИИ.
"""

from __future__ import annotations

import json
import re
import time

import anthropic

from app.config import Settings, get_settings

CACHE_TTL_SECONDS = 600
CACHE_MAX_ENTRIES = 50

SYSTEM_PROMPT = """Ты — поисковая система по заголовкам документов требований.
Тебе дают запрос пользователя и список документов (id и заголовок).
Отбери документы, которые ПО СМЫСЛУ соответствуют запросу: синонимы,
родственные понятия, другие формулировки того же. Не требуй совпадения слов.

Ответ строго JSON без markdown-обёртки:
{"matches": [{"id": <id из списка>, "score": <число 0..1>}, ...]}

score — насколько заголовок подходит запросу (1 — точное попадание).
Не выдумывай id вне списка. Если не подходит ничего — пустой список "matches".
Отсортируй по убыванию score, максимум 20 позиций."""


class SemanticSearchError(Exception):
    """Технический сбой семантического поиска (сеть, ключ, неразборчивый ответ)."""


def build_user_prompt(query: str, docs: list[tuple[int, str]]) -> str:
    lines = [f"Запрос: {query}", "", "Документы:"]
    lines += [f"{doc_id}. {title}" for doc_id, title in docs]
    return "\n".join(lines)


def parse_matches(raw_text: str, known_ids: set[int]) -> list[tuple[int, float]]:
    """Разобрать ответ модели: только известные id, score в 0..1, без дублей."""
    cleaned = raw_text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("в ответе нет JSON-объекта")
    data = json.loads(cleaned[start : end + 1])

    best: dict[int, float] = {}
    for item in data.get("matches", []):
        if not isinstance(item, dict):
            continue
        try:
            doc_id = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if doc_id not in known_ids:
            continue
        try:
            score = float(item.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        score = min(1.0, max(0.0, score))
        best[doc_id] = max(best.get(doc_id, 0.0), score)

    return sorted(best.items(), key=lambda pair: pair[1], reverse=True)


class SemanticSearcher:
    """Ранжирование заголовков через Anthropic-совместимый API с GLM.

    client передаётся в тестах; в проде создаётся лениво из настроек.
    """

    def __init__(self, client=None, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._client = client
        self._cache: dict[tuple[int, str], tuple[float, list[tuple[int, float]]]] = {}

    def _get_client(self):
        if self._client is None:
            self._client = anthropic.Anthropic(
                api_key=self._settings.ai_api_key,
                base_url=self._settings.ai_base_url,
                timeout=60.0,
                max_retries=2,
            )
        return self._client

    def search(
        self, analyst_id: int, query: str, docs: list[tuple[int, str]]
    ) -> list[tuple[int, float]]:
        """Вернуть [(document_id, score)], отсортировано по убыванию score."""
        key = (analyst_id, query.strip().lower())
        cached = self._cache.get(key)
        if cached is not None:
            stamped_at, matches = cached
            if time.monotonic() - stamped_at < CACHE_TTL_SECONDS:
                return matches

        try:
            response = self._get_client().messages.create(
                model=self._settings.ai_search_model,
                max_tokens=1000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_prompt(query, docs)}],
            )
        except anthropic.APIError as exc:
            raise SemanticSearchError(f"ошибка ИИ: {exc}") from exc

        text = "".join(
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        ).strip()
        try:
            matches = parse_matches(text, {doc_id for doc_id, _ in docs})
        except (ValueError, json.JSONDecodeError) as exc:
            raise SemanticSearchError(f"не удалось разобрать ответ ИИ: {exc}") from exc

        self._cache[key] = (time.monotonic(), matches)
        if len(self._cache) > CACHE_MAX_ENTRIES:
            oldest = sorted(self._cache.items(), key=lambda kv: kv[1][0])
            for stale_key, _ in oldest[: len(self._cache) - CACHE_MAX_ENTRIES]:
                del self._cache[stale_key]
        return matches
