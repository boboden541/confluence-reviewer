"""Юнит-тесты хранилища шаблона: нормализация, развёртка, дубликаты."""

from __future__ import annotations

from app.usecase.templates import (
    expand_sections,
    find_duplicate_sections,
    marker_from_pattern,
    normalize_sections,
)


def test_marker_from_pattern():
    assert marker_from_pattern("\\[СТ\\]") == "СТ"
    assert marker_from_pattern("СТ") == "СТ"
    assert marker_from_pattern("^\\[GDS\\]$") == "GDS"
    assert marker_from_pattern("") == ""


def test_normalize_sections_clamps_level_holes():
    # Ур.3 сразу после Ур.1 становится Ур.2 — «дыр» в иерархии нет
    sections = normalize_sections(
        [
            {"level": 1, "text": "Введение", "required": True},
            {"level": 3, "text": "Прыжок", "required": False},
        ]
    )
    assert [s["level"] for s in sections] == [1, 2]


def test_normalize_sections_bounds_and_cleanup():
    sections = normalize_sections(
        [
            {"level": 0, "text": "Слишком мелкий", "required": False},
            {"level": 9, "text": "Слишком глубокий", "required": False},
            {"level": 1, "text": "   Двойные  пробелы  ", "required": True},
            {"level": 1, "text": "", "required": True},  # пустое имя — не сохраняем
            {"level": 1, "text": "   ", "required": True},
        ]
    )
    assert [s["level"] for s in sections] == [1, 2, 1]
    assert sections[2]["text"] == "Двойные пробелы"


def test_normalize_sections_aliases():
    sections = normalize_sections(
        [
            {
                "level": 1,
                "text": "Полезные артефакты",
                "required": False,
                "aliases": [
                    "  Полезные   ресурсы ",  # пробелы схлопываются
                    "полезные артефакты",  # дубликат названия — отбрасываем
                    "",
                    None,  # type: ignore[dict-item]
                ],
            }
        ]
    )
    assert sections[0]["aliases"] == ["Полезные ресурсы"]


def test_expand_sections_parent_and_order():
    flat = [
        {"level": 1, "text": "Введение", "required": True},
        {"level": 2, "text": "Общая информация", "required": True, "aliases": ["Общее"]},
        {"level": 2, "text": "История", "required": False},
        {"level": 1, "text": "Общее описание", "required": True},
        {"level": 3, "text": "Глубокий", "required": False},
    ]
    expanded = expand_sections(flat)
    assert expanded[1]["parent"] == "Введение"
    assert expanded[2]["parent"] == "Введение"
    assert "parent" not in expanded[3]  # верхний уровень — без родителя
    assert expanded[3]["order"] == 2  # порядок только у разделов верхнего уровня
    assert expanded[1]["aliases"] == ["Общее"]
    # родитель Ур.3 — ближайший предыдущий раздел уровнем выше
    assert expanded[4]["parent"] == "Общее описание"


def test_find_duplicate_sections_same_parent_only():
    sections = [
        {"level": 1, "text": "Раздел А"},
        {"level": 2, "text": "Риски"},
        {"level": 1, "text": "Раздел Б"},
        {"level": 2, "text": "Риски"},  # другой родитель — допустимо
    ]
    assert find_duplicate_sections(sections) is None

    duplicate = [
        {"level": 1, "text": "Раздел А"},
        {"level": 2, "text": "Риски"},
        {"level": 2, "text": "риски "},  # тот же родитель — дубликат
    ]
    assert find_duplicate_sections(duplicate) == "риски "
