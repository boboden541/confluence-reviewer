"""Скриптовая валидация документа на соответствие шаблону (ФТ-CR-10).

Проверки:
- заголовок страницы соответствует title_pattern (например, содержит «[СТ]»);
- обязательные разделы присутствуют (сравнение без учёта регистра, по префиксу —
  допускаются суффиксы вида «Функциональные требования (BackEnd)»);
- подразделы внутри родителя (Общая информация под Введение и т.п.);
- в каждом повторяемом блоке доработки есть обязательные дочерние разделы;
- порядок разделов верхнего уровня (нарушение — замечание, не провал).

passed = нет критичных замечаний (отсутствие обязательных разделов).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup

# символы, которые могут отделять имя раздела от суффикса
_BOUNDARY = set(" (:.—–-/«\"',")


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


def heading_matches(actual_norm: str, required_norm: str) -> bool:
    """actual начинается с required и либо совпадает, либо за ним идёт разделитель."""
    if actual_norm == required_norm:
        return True
    if not actual_norm.startswith(required_norm):
        return False
    tail = actual_norm[len(required_norm) :]
    return bool(tail) and tail[0] in _BOUNDARY


def extract_headings(content_html: str) -> list[Heading]:
    """Заголовки h1..h4 из storage-формата Confluence (XHTML)."""
    soup = BeautifulSoup(content_html or "", "lxml")
    headings: list[Heading] = []
    for position, tag in enumerate(soup.find_all(re.compile(r"^h[1-4]$"))):
        text = tag.get_text(" ", strip=True)
        if text:
            headings.append(Heading(level=int(tag.name[1]), text=text, position=position))
    return headings


def find_heading(
    headings: list[Heading], level: int, names: list[str], start_after: int = -1
) -> Heading | None:
    """Первый заголовок уровня level, совпадающий с одним из имён (с префикс-допуском)."""
    for heading in headings:
        if heading.position <= start_after or heading.level != level:
            continue
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


def _load_template(template_file: str) -> dict:
    """Шаблон ищется: как указано (abs/от cwd), затем от корня backend и от app/."""
    candidates = [Path(template_file)]
    if not Path(template_file).is_absolute():
        backend_root = Path(__file__).resolve().parent.parent.parent
        candidates.append(backend_root / template_file)
        candidates.append(backend_root / "app" / Path(template_file).name)
    for path in candidates:
        if path.is_file():
            with path.open(encoding="utf-8") as fh:
                return json.load(fh)
    raise FileNotFoundError(f"Файл шаблона не найден: {template_file}")


def _check_blocks(
    template: dict, headings: list[Heading], findings: list[Finding]
) -> None:
    """Повторяемые блоки доработок: обязательные дочерние разделы в каждом блоке."""
    for block in template.get("repeatable_blocks", []):
        marker = find_heading(
            headings,
            block["marker_level"],
            [block["marker_text"]],
        )
        if marker is None:
            continue  # отсутствие самого маркера уже зафиксировано в sections
        scope_end = _section_scope_end(headings, marker)
        child_level = block["child_level"]
        required_children: list[str] = block.get("required_children", [])
        prefix = block.get("child_prefix")

        children = [
            h
            for h in headings
            if h.position > marker.position
            and h.position < scope_end
            and h.level == child_level
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
                    and h.level == child_level + 1
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


def validate_title(title: str, pattern: str) -> Finding | None:
    if not re.search(pattern, title or ""):
        return Finding(
            f"Заголовок страницы не соответствует шаблону: ожидается маркер «{pattern}»"
            f" (например, «1. [СТ] - Название доработки»); фактически: «{title or '—'}»",
            critical=True,
        )
    return None


def validate_template(
    title: str, content_html: str, template_file: str | None = None
) -> TemplateValidationResult:
    """Главная функция скриптовой валидации (ФТ-CR-10)."""
    from app.config import get_settings

    template = _load_template(template_file or get_settings().template_file)
    headings = extract_headings(content_html)
    findings: list[Finding] = []

    title_finding = validate_title(title, template.get("title_pattern", ""))
    if title_finding:
        findings.append(title_finding)

    if not headings:
        findings.append(
            Finding("В документе не найдено ни одного заголовка (h1–h4)", critical=True)
        )
        return _render(template, findings)

    # 1. Обязательные разделы и подразделы
    for section in template.get("sections", []):
        names = [section["text"], *section.get("aliases", [])]
        search_from = -1
        if section.get("parent"):
            parent = find_heading(headings, section["level"] - 1, [section["parent"]])
            if parent is None:
                continue  # родитель отсутствует — ошибка уже выдана по нему
            search_from = parent.position
            scope_end = _section_scope_end(headings, parent)
            found = next(
                (
                    h
                    for h in headings
                    if search_from < h.position < scope_end
                    and h.level == section["level"]
                    and any(heading_matches(h.norm, normalize_heading(n)) for n in names)
                ),
                None,
            )
        else:
            found = find_heading(headings, section["level"], names, start_after=search_from)

        if found is None and section.get("required"):
            where = f" (внутри «{section['parent']}»)" if section.get("parent") else ""
            findings.append(
                Finding(
                    f"Отсутствует обязательный раздел «{section['text']}»{where}",
                    critical=True,
                )
            )

    # 2. Повторяемые блоки доработок
    _check_blocks(template, headings, findings)

    # 3. Порядок разделов верхнего уровня (некритично)
    ordered = [
        s for s in template.get("sections", []) if s.get("order") and not s.get("parent")
    ]
    ordered.sort(key=lambda s: s["order"])
    last_position = -1
    for section in ordered:
        names = [section["text"], *section.get("aliases", [])]
        heading = find_heading(headings, section["level"], names)
        if heading is None:
            continue
        if heading.position < last_position:
            findings.append(
                Finding(
                    f"Раздел «{section['text']}» идёт раньше, чем предусмотрено шаблоном",
                    critical=False,
                )
            )
        last_position = max(last_position, heading.position)

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
