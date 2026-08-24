"""Хранение шаблона требований в БД с историей версий.

Первая версия сеется из app/templates/requirements_template.json. Каждое
сохранение из UI создаёт новую версию; активна ровно одна (is_active).

Секции хранятся плоским списком в визуальном порядке: вложенность задаётся
уровнем 1..3, parent/order для скриптового валидатора вычисляются на лету
(expand_sections). «Дыр» в иерархии нет: после Ур.1 раздел Ур.3
нормализуется в Ур.2 — то же правило показывает предпросмотр в UI.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TemplateVersion

MAX_LEVEL = 3
_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


def _seed_path() -> Path | None:
    """Файл первичного шаблона: как указано в настройках, затем от корня backend."""
    from app.config import get_settings

    configured = Path(get_settings().template_file)
    candidates = (
        [configured]
        if configured.is_absolute()
        else [_BACKEND_ROOT / configured, _BACKEND_ROOT / "app" / configured.name]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def marker_from_pattern(pattern: str) -> str:
    """Старый regex-маркер → буквальное вхождение: «\\[СТ\\]» → «СТ»."""
    cleaned = pattern.strip().lstrip("^").rstrip("$").replace("\\", "")
    if len(cleaned) >= 2 and cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1]
    return cleaned.strip()


def _clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_sections(sections: list[dict]) -> list[dict]:
    """Чистка перед сохранением: тексты без двойных пробелов, уровни 1..3
    без «дыр», пустые алиасы и алиасы-дубликаты названия отбрасываются."""
    result: list[dict] = []
    prev_level = 0
    for section in sections:
        text = _clean_text(section.get("text"))
        if not text:
            continue
        level = min(max(int(section.get("level", 1)), 1), MAX_LEVEL)
        level = min(level, prev_level + 1)  # Ур.3 сразу после Ур.1 → Ур.2
        prev_level = level
        aliases: list[str] = []
        for alias in section.get("aliases") or []:
            cleaned = _clean_text(alias)
            if cleaned and cleaned.lower() != text.lower():
                aliases.append(cleaned)
        result.append(
            {"level": level, "text": text, "required": bool(section.get("required")), "aliases": aliases}
        )
    return result


def expand_sections(flat: list[dict]) -> list[dict]:
    """Плоский список → формат скриптового валидатора: parent — ближайший
    предыдущий раздел уровнем выше, order — номер среди разделов Ур.1."""
    expanded: list[dict] = []
    stack: list[tuple[int, str]] = []
    top_order = 0
    for section in flat:
        level = int(section["level"])
        while stack and stack[-1][0] >= level:
            stack.pop()
        item: dict = {
            "level": level,
            "text": section["text"],
            "required": bool(section.get("required", False)),
        }
        if section.get("aliases"):
            item["aliases"] = list(section["aliases"])
        if stack:
            item["parent"] = stack[-1][1]
        else:
            top_order += 1
            item["order"] = top_order
        expanded.append(item)
        stack.append((level, section["text"]))
    return expanded


def find_duplicate_sections(sections: list[dict]) -> str | None:
    """Повторяющееся название среди детей одного родителя (или None).

    Одинаковые названия на одном уровне под разными родителями допустимы —
    валидатор ищет подразделы внутри области конкретного родителя.
    """
    stack: list[tuple[int, str]] = []
    seen: set[tuple[int, str, str]] = set()
    for section in sections:
        level = int(section["level"])
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1] if stack else ""
        key = (level, parent.lower(), str(section["text"]).strip().lower())
        if key in seen:
            return str(section["text"])
        seen.add(key)
        stack.append((level, str(section["text"])))
    return None


def load_seed_file() -> dict | None:
    """Первая версия шаблона из JSON-файла (legacy-формат → новый)."""
    path = _seed_path()
    if path is None:
        return None
    with path.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    return {
        "name": raw.get("name") or "Шаблон требований",
        "description": raw.get("description"),
        "title_marker": marker_from_pattern(raw.get("title_pattern", "")),
        "sections": normalize_sections(
            [
                {
                    "level": s.get("level", 1),
                    "text": s.get("text", ""),
                    "required": bool(s.get("required")),
                    "aliases": s.get("aliases", []),
                }
                for s in raw.get("sections", [])
            ]
        ),
        "repeatable_blocks": raw.get("repeatable_blocks", []),
    }


def get_active(db: Session) -> TemplateVersion | None:
    return db.scalar(
        select(TemplateVersion)
        .where(TemplateVersion.is_active)
        .order_by(TemplateVersion.id.desc())
    )


def seed_if_missing(db: Session) -> TemplateVersion | None:
    """Залить первую версию из файла, если в БД ещё нет шаблона."""
    if get_active(db) is not None:
        return None
    seed = load_seed_file()
    if seed is None:
        return None
    version = TemplateVersion(
        name=seed["name"],
        description=seed["description"],
        title_marker=seed["title_marker"],
        sections_json=json.dumps(seed["sections"], ensure_ascii=False),
        repeatable_blocks_json=json.dumps(seed["repeatable_blocks"], ensure_ascii=False),
        is_active=True,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


def save_version(
    db: Session, *, title_marker: str, sections: list[dict]
) -> TemplateVersion:
    """Новая активная версия. name/description и повторяемые блоки
    редактируются только в файле и переносятся из предыдущей версии."""
    previous = get_active(db)
    version = TemplateVersion(
        name=previous.name if previous else "Шаблон требований",
        description=previous.description if previous else None,
        title_marker=title_marker.strip(),
        sections_json=json.dumps(sections, ensure_ascii=False),
        repeatable_blocks_json=previous.repeatable_blocks_json if previous else "[]",
        is_active=True,
    )
    if previous is not None:
        previous.is_active = False
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


def version_to_dict(version: TemplateVersion) -> dict:
    """Активная версия → dict для скриптового валидатора."""
    return {
        "title_marker": version.title_marker,
        "sections": expand_sections(json.loads(version.sections_json)),
        "repeatable_blocks": json.loads(version.repeatable_blocks_json or "[]"),
    }


def get_template_for_validation(
    db: Session, version_id: int | None = None
) -> tuple[dict, int] | None:
    """Шаблон для проверки документа: (словарь для валидатора, id версии).

    version_id — конкретная версия, выбранная пользователем в диалоге
    проверки (пока выбор один — активная). None — активная версия;
    если БД пуста, сеем из файла (страховка для первого запуска и тестов).
    """
    if version_id is not None:
        version = db.get(TemplateVersion, version_id)
        return (version_to_dict(version), version.id) if version is not None else None
    active = get_active(db) or seed_if_missing(db)
    return (version_to_dict(active), active.id) if active is not None else None
