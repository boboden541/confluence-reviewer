"""Справочник ИИ-критериев и сборка промта запуска из них.

Критерии глобальные (раздел настроек «Критерии ИИ-проверок»): название +
промт-инструкция. Промт ИИ-проверки в диалоге запуска собирается из
отмеченных активных критериев по схеме «каркас + нумерованные блоки»;
снятие замка превращает его в override на один запуск. Изменение промта
критерия меняет собранный промт → хэш в отчёте → перевалидация (ФТ-CR-14).
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app import repository
from app.models import AiCriterion
from app.usecase.exceptions import CriterionNotFound, CriterionSelectionError

# Каркас собранного промта: блоки критериев вставляются между головой и хвостом.
# Хвост — правила и JSON-контракт ответа (парсится в clients.ai_validator).
PROMPT_HEAD = """Ты — опытный ведущий системный аналитик, ревьюер технических требований.

Тебе дают документ требований (в Markdown), созданный аналитиком в Confluence.
Оцени качество содержимого по критериям:

"""

PROMPT_TAIL = """
Правила:
- Проверяй документ строго по перечисленным выше критериям. Замечание,
  не относящееся ни к одному из них, не выдвигай — даже если оно кажется важным.
- Ссылайся на раздел документа, к которому относится замечание.
- Не выдумывай проблем: замечание только если из текста это действительно следует.
- minor — стилистические шероховатости; major — существенный пробел или риск;
  critical — документ невозможно реализовать или требования противоречат друг другу.

Ответ строго в JSON без markdown-обёртки:
{
  "passed": true|false,
  "summary": "краткое заключение в 1-3 предложениях",
  "findings": [
    {
      "criterion": "название одного из перечисленных критериев",
      "severity": "critical|major|minor",
      "message": "конкретное замечание с указанием раздела"
    }
  ]
}
Если замечаний нет — "passed": true и пустой список findings."""

# Стартовое наполнение пустого справочника — три критерия действовавшего
# ранее монолитного промта (clients.ai_validator.SYSTEM_PROMPT), чтобы
# переход на справочник не менял поведение существующей установки.
SEED_CRITERIA: list[tuple[str, str]] = [
    (
        "Полнота описания",
        "описаны ли все сценарии использования доработки, граничные и ошибочные "
        "ситуации, предусловия и постусловия. Разработчику не должно понадобиться "
        "что-то додумывать.",
    ),
    (
        "Непротиворечивость требований",
        "нет ли противоречий между разделами документа (разные форматы данных, "
        "несовместимые правила, конфликтующие сценарии).",
    ),
    (
        "Однозначность формулировок",
        "сможет ли разработчик реализовать требования без дополнительных "
        "уточнений: нет ли расплывчатых формулировок («по необходимости», "
        "«должно работать быстро»), неопределённых терминов, требований без "
        "критериев проверки.",
    ),
]

# Транслитерация кириллицы для кода критерия (латиница + подчёркивания)
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slugify_code(name: str) -> str:
    """Человекочитаемый код из названия: транслит, не-буквы → «_».

    Пустой результат (название целиком из символов) — нейтральное «criterion».
    """
    lowered = name.lower()
    translated = "".join(_TRANSLIT.get(ch, ch) for ch in lowered)
    code = re.sub(r"[^a-z0-9]+", "_", translated).strip("_")[:48]
    return code or "criterion"


def _unique_code(db: Session, base: str) -> str:
    """Свободный код: base, base_2, base_3… — код неизменен после создания."""
    code = base
    suffix = 1
    while repository.criteria.code_exists(db, code):
        suffix += 1
        code = f"{base}_{suffix}"
    return code


def seed_criteria_if_missing(db: Session, owner_user_id: int | None = None) -> None:
    """Пустой личный справочник наполняем стартовыми критериями (идемпотентно).
    Без явного владельца — God (если уже создан seed_auth'ом)."""
    if repository.criteria.any_exists(db):
        return
    if owner_user_id is None:
        from app.usecase.auth import default_owner_id

        owner_user_id = default_owner_id(db)
    for name, prompt in SEED_CRITERIA:
        db.add(
            AiCriterion(
                code=_unique_code(db, slugify_code(name)),
                name=name,
                prompt=prompt,
                owner_user_id=owner_user_id,
            )
        )
    db.commit()


def list_criteria(db: Session, owner_user_id: int | None = None) -> list[AiCriterion]:
    """Критерии владельца: активные, затем архивные."""
    all_criteria = repository.criteria.list_all(db)
    if owner_user_id is not None:
        all_criteria = [c for c in all_criteria if c.owner_user_id == owner_user_id]
    return all_criteria


def get_criterion(db: Session, criterion_id: int) -> AiCriterion:
    """Критерий по id; отсутствие — доменная ошибка."""
    criterion = repository.criteria.get(db, criterion_id)
    if criterion is None:
        raise CriterionNotFound("Критерий не найден")
    return criterion


def select_criteria(
    db: Session,
    criterion_ids: list[int] | None = None,
    owner_user_id: int | None = None,
) -> list[AiCriterion]:
    """Критерии прогона владельца: выбранные (id, в порядке передачи) или
    все его активные.

    Выбранный id, отсутствующий в БД или в архиве, — ошибка запроса: молча
    вычеркивать нельзя, промт прогона незаметно изменился бы.
    """
    if criterion_ids is None:
        active = repository.criteria.list_active(db)
        if owner_user_id is not None:
            active = [c for c in active if c.owner_user_id == owner_user_id]
        return active
    ordered = dict.fromkeys(criterion_ids)  # дубликаты схлопываем, порядок сохраняем
    criteria: list[AiCriterion] = []
    for criterion_id in ordered:
        criterion = repository.criteria.get(db, criterion_id)
        if criterion is None:
            raise CriterionSelectionError(f"Критерий ИИ-проверки {criterion_id} не найден")
        if criterion.is_archived:
            raise CriterionSelectionError(
                f"Критерий «{criterion.name}» в архиве — выберите активный"
            )
        criteria.append(criterion)
    return criteria


def assemble_prompt(criteria: list[AiCriterion]) -> str:
    """Собрать промт прогона: каркас + нумерованные блоки критериев."""
    blocks = [
        f"{i}. «{c.name}» — {c.prompt}" for i, c in enumerate(criteria, start=1)
    ]
    return PROMPT_HEAD + "\n".join(blocks) + PROMPT_TAIL


def copy_criterion(
    db: Session, criterion: AiCriterion, *, owner_user_id: int | None
) -> AiCriterion:
    """Копия критерия из общего реестра себе: имя как у оригинала; если у
    владельца уже есть критерий с таким именем — «{name} (2)», « (3)»…
    Код — свободный слуг того же имени (совпадёт с оригиналом → «_2»)."""
    existing = {c.name for c in list_criteria(db, owner_user_id=owner_user_id)}
    candidate, counter = criterion.name, 2
    while candidate in existing:
        candidate = f"{criterion.name} ({counter})"
        counter += 1
    copy = AiCriterion(
        code=_unique_code(db, slugify_code(candidate)),
        name=candidate,
        prompt=criterion.prompt,
        owner_user_id=owner_user_id,
    )
    db.add(copy)
    db.commit()
    db.refresh(copy)
    return copy
