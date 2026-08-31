"""Скриптовая валидация документа на соответствие шаблону (ФТ-CR-10).

Шаблон передаётся словарём (активная версия из БД, см. usecase.templates):
title_marker + sections (с вычисленными parent/order) + repeatable_blocks.

Проверки мягкие (по замечаниям заказчика): у аналитиков структура свободная —
- заголовок страницы содержит маркер отдельным словом («[СТ]», «СТ-15» …);
- обязательные разделы должны присутствовать; порядок разделов и их уровни
  (вложенность) могут отличаться от шаблона — это не замечание;
- совпадение имён неточное: без учёта регистра, одно название внутри другого
  («Общая информация о сервисе» ≈ «Общая информация»), тот же набор слов в
  другом порядке («Информация общая») или похожесть текста
  («Критерий приёмки» ≈ «Критерии приёмки»);
- в каждом повторяемом блоке доработки есть обязательные дочерние разделы.

passed = нет критичных замечаний (отсутствие обязательных разделов).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from bs4 import BeautifulSoup

# неточное совпадение: порог похожести и минимальная длина для него
# (короче 6 символов — только точное совпадение: «риски» не должно
# «входить» в произвольные слова документа)
_FUZZY_RATIO = 0.8
_FUZZY_MIN_LEN = 6


@dataclass(slots=True)
class Finding:
    message: str
    critical: bool  # критичное замечание проваливает проверку шаблона


@dataclass(slots=True)
class TemplateValidationResult:
    passed: bool
    findings_markdown: str
    critical_count: int = 0
    warning_count: int = 0


@dataclass(slots=True)
class Heading:
    level: int
    text: str  # как в документе (очищенный текст)
    position: int

    @property
    def norm(self) -> str:
        return normalize_heading(self.text)


def normalize_heading(text: str) -> str:
    """Нормализация для сравнения: пробелы схлопнуты, без «*» и регистра."""
    cleaned = re.sub(r"\s+", " ", text.replace("*", " ")).strip().lower()
    return cleaned


def _words(text: str) -> set[str]:
    """Значимые слова (от 3 символов) — для сравнения без учёта порядка."""
    return {word for word in re.split(r"\W+", text) if len(word) >= 3}


def heading_matches(actual_norm: str, required_norm: str) -> bool:
    """Неточное вхождение: точное совпадение, вхождение одного названия
    в другое, тот же набор слов в другом порядке или похожесть по символам
    ≥ 0.8 (регистр не важен).

    Ловит «Общая информация о сервисе» ≈ «Общая информация»,
    «Информация общая» (перестановка слов), «Критерий приёмки» ≈ «Критерии
    приёмки». Короткие названия (короче 6 символов) сравниваются только
    точно — иначе слишком много ложных срабатываний.
    """
    if not required_norm or not actual_norm:
        return False
    if actual_norm == required_norm:
        return True
    if len(required_norm) < _FUZZY_MIN_LEN or len(actual_norm) < _FUZZY_MIN_LEN:
        return False
    if required_norm in actual_norm or actual_norm in required_norm:
        return True
    # перестановка слов: «Информация общая» ≈ «Общая информация»
    actual_words, required_words = _words(actual_norm), _words(required_norm)
    if required_words and (required_words <= actual_words or actual_words <= required_words):
        return True
    return SequenceMatcher(None, required_norm, actual_norm).ratio() >= _FUZZY_RATIO


def extract_headings(content_html: str) -> list[Heading]:
    """Заголовки h1..h4 из storage-формата Confluence (XHTML)."""
    soup = BeautifulSoup(content_html or "", "lxml")
    headings: list[Heading] = []
    for position, tag in enumerate(soup.find_all(re.compile(r"^h[1-4]$"))):
        text = tag.get_text(" ", strip=True)
        if text:
            headings.append(Heading(level=int(tag.name[1]), text=text, position=position))
    return headings


def find_heading(headings: list[Heading], names: list[str]) -> Heading | None:
    """Первый заголовок с любым уровнем, неточно совпадающий с одним из имён.

    Уровень не фильтруем: у аналитиков вложенность может отличаться
    от шаблона — важно наличие раздела, а не его место в иерархии.
    """
    for heading in headings:
        for name in names:
            if heading_matches(heading.norm, normalize_heading(name)):
                return heading
    return None


def _section_scope_end(headings: list[Heading], parent: Heading) -> int:
    """Позиция, где заканчивается раздел parent (следующий заголовок того же или выше уровня)."""
    for heading in headings:
        if heading.position > parent.position and heading.level <= parent.level:
            return heading.position
    return len(headings) + 1


def _check_blocks(
    template: dict, headings: list[Heading], findings: list[Finding]
) -> None:
    """Повторяемые блоки доработок: обязательные дочерние разделы в каждом блоке.

    Уровни в шаблоне не фильтруют поиск (могут отличаться у аналитиков):
    маркер ищется на любом уровне, дети — уровнем ниже фактического уровня
    маркера в документе.
    """
    for block in template.get("repeatable_blocks", []):
        marker = find_heading(headings, [block["marker_text"]])
        if marker is None:
            continue  # отсутствие самого маркера уже зафиксировано в sections
        scope_end = _section_scope_end(headings, marker)
        required_children: list[str] = block.get("required_children", [])
        prefix = block.get("child_prefix")

        children = [
            h
            for h in headings
            if h.position > marker.position
            and h.position < scope_end
            and h.level == marker.level + 1
            and (prefix is None or heading_matches(h.norm, normalize_heading(prefix)))
        ]
        if not children:
            if block.get("required_block", False):
                findings.append(
                    Finding(
                        f"В разделе «{marker.text}» нет ни одного блока"
                        f"{' («' + prefix + '…»)' if prefix else ''} — доработки не описаны",
                        critical=True,
                    )
                )
            continue

        for child in children:
            child_end = _section_scope_end(headings, child)
            for required in required_children:
                found = any(
                    h.position > child.position
                    and h.position < child_end
                    and h.level == child.level + 1
                    and heading_matches(h.norm, normalize_heading(required))
                    for h in headings
                )
                if not found:
                    findings.append(
                        Finding(
                            f"Блок «{child.text}»: отсутствует обязательный подраздел «{required}»",
                            critical=True,
                        )
                    )


def validate_title(title: str, marker: str) -> Finding | None:
    """Маркер названия — буквальное вхождение отдельным словом, регистр не важен.

    «СТ» найдётся в «[СТ] GDS-15» и «СТ-15 Доработка», но не в «Структура»
    или «Просто страница» (вхождение внутри слова не считается).
    """
    marker = (marker or "").strip()
    if not marker:
        return None  # маркер не задан — подходит любое название
    pattern = rf"(?<!\w){re.escape(marker)}(?!\w)"
    if not re.search(pattern, title or "", flags=re.IGNORECASE):
        return Finding(
            f"Заголовок страницы не содержит маркер «{marker}»"
            f" (например, «1. [СТ] — Название доработки»); фактически: «{title or '—'}»",
            critical=True,
        )
    return None


def validate_template(title: str, content_html: str, template: dict) -> TemplateValidationResult:
    """Главная функция скриптовой валидации (ФТ-CR-10).

    template — активная версия шаблона из БД (usecase.templates).
    """
    headings = extract_headings(content_html)
    findings: list[Finding] = []

    title_finding = validate_title(title, template.get("title_marker", ""))
    if title_finding:
        findings.append(title_finding)

    if not headings:
        findings.append(
            Finding("В документе не найдено ни одного заголовка (h1–h4)", critical=True)
        )
        return _render(template, findings)

    # 1. Обязательные разделы. Порядок, уровень и конкретный родитель не важны
    #    (структура у аналитиков свободная) — проверяем наличие по имени.
    for section in template.get("sections", []):
        names = [section["text"], *section.get("aliases", [])]
        if find_heading(headings, names) is None and section.get("required"):
            findings.append(
                Finding(f"Отсутствует обязательный раздел «{section['text']}»", critical=True)
            )

    # 2. Повторяемые блоки доработок
    _check_blocks(template, headings, findings)

    return _render(template, findings)


def _render(template: dict, findings: list[Finding]) -> TemplateValidationResult:
    critical = [f for f in findings if f.critical]
    warnings = [f for f in findings if not f.critical]
    lines: list[str] = []
    if not findings:
        lines.append("✅ Документ соответствует шаблону требований.")
    else:
        if critical:
            lines.append(f"### ❌ Критичные замечания ({len(critical)})")
            lines.extend(f"- ❌ {f.message}" for f in critical)
        if warnings:
            lines.append(f"### ⚠️ Замечания ({len(warnings)})")
            lines.extend(f"- ⚠️ {f.message}" for f in warnings)
    return TemplateValidationResult(
        passed=not critical,
        findings_markdown="\n".join(lines),
        critical_count=len(critical),
        warning_count=len(warnings),
    )
