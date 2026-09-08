"""Хранение шаблонов требований в БД с историей версий.

Шаблон — контейнер (таблица templates: пометка «по умолчанию», архив);
каждое сохранение из UI создаёт новую версию, активна ровно одна внутри
шаблона. Первый шаблон сеется из app/templates/requirements_template.json.

Секции хранятся плоским списком в визуальном порядке: вложенность задаётся
уровнем 1..3, parent/order для скриптового валидатора вычисляются на лету
(expand_sections). «Дыр» в иерархии нет: после Ур.1 раздел Ур.3
нормализуется в Ур.2 — то же правило показывает предпросмотр в UI.

Выборки — в repository.templates; мутации (создание версий, пометки,
архив) остаются здесь.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy.orm import Session

from app import repository
from app.models import Template, TemplateVersion
from app.usecase.exceptions import TemplateNotFound
from app.utils import now_utc

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


def get_active_version(db: Session, template: Template) -> TemplateVersion | None:
    """Активная версия шаблона (внутри контейнера ровно одна)."""
    return repository.templates.get_active_version(db, template)


def list_templates(db: Session, owner_user_id: int | None = None) -> list[Template]:
    """Шаблоны владельца: активные (по умолчанию — первым, дальше свежие
    обновления), затем архивные (свежая архивация сверху)."""
    rows = repository.templates.list_containers(db)
    if owner_user_id is not None:
        rows = [t for t in rows if t.owner_user_id == owner_user_id]
    active = [t for t in rows if t.archived_at is None]
    archived = [t for t in rows if t.archived_at is not None]

    def freshness(t: Template) -> int:
        version = get_active_version(db, t)
        return version.id if version else 0

    active.sort(key=lambda t: (not t.is_default, -freshness(t)))
    archived.sort(key=lambda t: t.archived_at or now_utc(), reverse=True)
    return active + archived


def get_default_template(db: Session, owner_user_id: int | None = None) -> Template | None:
    template = repository.templates.get_default(db)
    if owner_user_id is not None and template is not None and template.owner_user_id != owner_user_id:
        return None
    return template


def get_active(db: Session, owner_user_id: int | None = None) -> TemplateVersion | None:
    """Legacy (/api/template): активная версия моего шаблона «по умолчанию»;
    если пометки нет — самого свежего моего неархивного шаблона."""
    template = repository.templates.get_default(db)
    if owner_user_id is not None and template is not None and template.owner_user_id != owner_user_id:
        template = None
    if template is None:
        template = next(
            (t for t in list_templates(db, owner_user_id=owner_user_id) if t.archived_at is None),
            None,
        )
    return get_active_version(db, template) if template else None


def get_template(db: Session, template_id: int) -> Template:
    """Шаблон по id; отсутствие — доменная ошибка (api → 404)."""
    template = repository.templates.get(db, template_id)
    if template is None:
        raise TemplateNotFound("Шаблон не найден")
    return template


def list_versions(db: Session, template_id: int) -> list[TemplateVersion]:
    """История версий шаблона, свежие сверху."""
    return repository.templates.list_versions_desc(db, template_id)


def find_name_duplicate(
    db: Session, name: str, exclude_id: int | None = None, owner_user_id: int | None = None
) -> Template | None:
    """Неархивный шаблон владельца с таким названием (регистр не важен)."""
    needle = name.strip().lower()
    for template in repository.templates.list_not_archived(db):
        if template.id == exclude_id:
            continue
        if owner_user_id is not None and template.owner_user_id != owner_user_id:
            continue
        version = get_active_version(db, template)
        if version is not None and version.name.strip().lower() == needle:
            return template
    return None


def seed_if_missing(db: Session, owner_user_id: int | None = None) -> TemplateVersion | None:
    """Залить первый шаблон из файла, если в БД ещё нет ни одного. Без явного
    владельца — God (если уже создан seed_auth'ом)."""
    if repository.templates.any_exists(db):
        return None
    if owner_user_id is None:
        from app.usecase.auth import default_owner_id

        owner_user_id = default_owner_id(db)
    seed = load_seed_file()
    if seed is None:
        return None
    template = Template(is_default=True, owner_user_id=owner_user_id)
    db.add(template)
    db.flush()  # id контейнера нужен версии
    version = TemplateVersion(
        template_id=template.id,
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


def create_template(
    db: Session,
    *,
    name: str,
    description: str | None,
    title_marker: str,
    sections: list[dict],
    owner_user_id: int | None = None,
) -> Template:
    """Новый шаблон с первой версией. Создаётся «с нуля»: повторяемых блоков
    доработок нет (они остаются особенностью сидированного шаблона)."""
    template = Template(owner_user_id=owner_user_id)
    db.add(template)
    db.flush()
    version = TemplateVersion(
        template_id=template.id,
        name=name.strip(),
        description=(description or "").strip() or None,
        title_marker=title_marker.strip(),
        sections_json=json.dumps(sections, ensure_ascii=False),
        repeatable_blocks_json="[]",
        is_active=True,
    )
    db.add(version)
    # первый шаблон владельца сразу становится «по умолчанию»
    others = [t for t in repository.templates.list_others(db, template.id)
              if t.owner_user_id == owner_user_id]
    if not any(t.is_default and t.archived_at is None for t in others):
        template.is_default = True
    db.commit()
    db.refresh(template)
    return template


def save_version(
    db: Session,
    template: Template,
    *,
    name: str,
    description: str | None,
    title_marker: str,
    sections: list[dict],
) -> TemplateVersion:
    """Новая активная версия шаблона. Повторяемые блоки не редактируются из
    UI и переносятся из предыдущей версии."""
    previous = get_active_version(db, template)
    version = TemplateVersion(
        template_id=template.id,
        name=name.strip(),
        description=(description or "").strip() or None,
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


def set_default(db: Session, template: Template) -> Template:
    """Пометка «по умолчанию»: предвыбор в диалоге проверки. Одна у владельца."""
    for other in repository.templates.list_others(db, template.id):
        if other.owner_user_id == template.owner_user_id:
            other.is_default = False
    template.is_default = True
    db.commit()
    db.refresh(template)
    return template


def archive_template(db: Session, template: Template) -> Template:
    """Шаблон в архив: исчезает из диалога проверки, карточка и история живы.
    Если он был «по умолчанию» — пометка переходит самому свежему из
    оставшихся шаблонов владельца."""
    template.archived_at = now_utc()
    if template.is_default:
        template.is_default = False
        remaining = [
            t
            for t in list_templates(db, owner_user_id=template.owner_user_id)
            if t.archived_at is None
        ]
        if remaining:
            set_default(db, remaining[0])
        else:
            db.commit()
    else:
        db.commit()
    db.refresh(template)
    return template


def restore_template(db: Session, template: Template) -> Template:
    """Вернуть из архива. Если пометки «по умолчанию» нет ни у кого —
    возвращённый становится «по умолчанию»."""
    template.archived_at = None
    if get_default_template(db) is None:
        template.is_default = True
    db.commit()
    db.refresh(template)
    return template


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
    проверки (активная версия выбранного шаблона). None — активная версия
    шаблона «по умолчанию»; если БД пуста, сеем из файла (страховка для
    первого запуска и тестов).
    """
    if version_id is not None:
        version = repository.templates.get_version(db, version_id)
        return (version_to_dict(version), version.id) if version is not None else None
    active = get_active(db) or seed_if_missing(db)
    return (version_to_dict(active), active.id) if active is not None else None


def copy_template(
    db: Session, template: Template, *, owner_user_id: int | None
) -> Template:
    """Копия шаблона из общего реестра себе: контейнер + активная версия
    целиком (секции, маркер, описания). Имя как у оригинала; при коллизии
    у владельца — «{name} (2)», « (3)»…"""
    source_version = get_active_version(db, template)
    if source_version is None:
        raise TemplateHasNoActiveVersion("У шаблона нет активной версии")
    candidate, counter = source_version.name, 2
    while find_name_duplicate(db, candidate, owner_user_id=owner_user_id) is not None:
        candidate = f"{source_version.name} ({counter})"
        counter += 1
    new_template = create_template(
        db,
        name=candidate,
        description=source_version.description,
        title_marker=source_version.title_marker,
        sections=json.loads(source_version.sections_json),
        owner_user_id=owner_user_id,
    )
    return new_template
