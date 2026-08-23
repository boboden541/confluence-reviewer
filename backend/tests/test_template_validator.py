"""Тесты скриптовой валидации шаблона (ФТ-CR-10) на реальной структуре MTSLIVE."""

from __future__ import annotations

from app.services.template_store import expand_sections, load_seed_file
from app.services.template_validator import (
    extract_headings,
    heading_matches,
    normalize_heading,
    validate_title,
    validate_template,
)

# Шаблон в том виде, в каком его отдаёт БД для валидатора (первая версия из файла)
_seed = load_seed_file()
SEED = {
    "title_marker": _seed["title_marker"],
    "sections": expand_sections(_seed["sections"]),
    "repeatable_blocks": _seed["repeatable_blocks"],
}


def h(level: int, text: str) -> str:
    return f"<h{level}>{text}</h{level}>"


GOOD_BODY = "".join(
    [
        h(1, "Введение"),
        h(2, "Общая информация"),
        h(2, "История изменений"),
        h(1, "Общее описание"),
        h(2, "Назначение документа"),
        h(2, "Контекст"),
        h(1, "Предлагаемое решение"),
        h(1, "Функциональные требования (BackEnd)"),
        h(2, "Создать таблицу-справочник"),
        h(3, "Общее описание"),
        h(3, "Описание доработок"),
        h(3, "Критерии приёмки"),
        h(3, "Документация по функционалу"),
        h(2, "Вторая доработка"),
        h(3, "Общее описание"),
        h(3, "Описание доработок"),
        h(3, "Критерии приёмки"),
        h(3, "Документация по функционалу"),
        h(1, "Требования к интерфейсам"),
        h(2, "Сценарии использования"),
        h(2, "Верстка интерфейса экрана «Настройки»"),
        h(3, "Общее описание"),
        h(3, "Описание доработок"),
        h(3, "Критерии приёмки"),
        h(3, "Документация по функционалу"),
        h(1, "Ревью требований"),
    ]
)


def test_good_document_passes():
    result = validate_template("[СТ] GDS-15 Загрузка кино", GOOD_BODY, SEED)
    assert result.passed, result.findings_markdown


def test_title_without_marker_fails():
    result = validate_template("Просто страница", GOOD_BODY, SEED)
    assert not result.passed
    assert "маркер" in result.findings_markdown


# --- маркер названия: буквальное вхождение отдельным словом ---


def test_title_marker_requires_standalone_word():
    # «СТ» внутри слова («Структура», «Просто») маркером не считается
    assert validate_title("Структура доработки", "СТ") is not None
    assert validate_title("Просто страница", "СТ") is not None
    # а отдельное слово — считается, даже в скобках или с дефисом
    assert validate_title("[СТ] GDS-15 Загрузка кино", "СТ") is None
    assert validate_title("1. СТ-15 Доработка", "СТ") is None
    assert validate_title("GDS-15 (ст)", "СТ") is None  # регистр не важен


def test_empty_title_marker_allows_any_title():
    assert validate_title("Что угодно", "") is None
    result = validate_template("Без маркера", GOOD_BODY, {**SEED, "title_marker": ""})
    assert "маркер" not in result.findings_markdown


def test_missing_required_section_fails():
    body = GOOD_BODY.replace(h(1, "Требования к интерфейсам"), "")
    result = validate_template("[СТ] Документ", body, SEED)
    assert not result.passed
    assert "Требования к интерфейсам" in result.findings_markdown


def test_missing_required_subsection_inside_parent():
    body = GOOD_BODY.replace(h(2, "Назначение документа"), "")
    result = validate_template("[СТ] Документ", body, SEED)
    assert not result.passed
    assert "Назначение документа" in result.findings_markdown


def test_fr_block_missing_child_section():
    body = GOOD_BODY.replace(
        h(2, "Вторая доработка") + h(3, "Общее описание") + h(3, "Описание доработок")
        + h(3, "Критерии приёмки") + h(3, "Документация по функционалу"),
        h(2, "Вторая доработка") + h(3, "Общее описание") + h(3, "Описание доработок")
        + h(3, "Критерий приёмки"),  # ед. число + нет документации
    )
    result = validate_template("[СТ] Документ", body, SEED)
    assert not result.passed
    assert "Критерии приёмки" in result.findings_markdown
    assert "Документация по функционалу" in result.findings_markdown


def test_real_gds15_example_structure_fails():
    """Структура реального документа GDS-15 (pageId=2380439645): без раздела ИТ,
    в блоках ФТ нет «Документации по функционалу», «Критерий приёмки» в ед. числе."""
    body = "".join(
        [
            h(1, "Введение"),
            h(2, "Общая информация"),
            h(2, "История изменений"),
            h(2, "Полезные ресурсы"),
            h(1, "Общее описание"),
            h(2, "Назначение документа"),
            h(2, "Контекст"),
            h(1, "Описание текущего состояния"),
            h(1, "Предлагаемое решение"),
            h(1, "Функциональные требования (BackEnd)"),
            h(2, "Создать таблицу-справочник dbo.data_source"),
            h(3, "Общее описание"),
            h(3, "Описание доработок"),
            h(3, "Критерии приёмки"),
            h(2, "Обновить performance_to_sale_channel – защита от DELETE"),
            h(3, "Общее описание"),
            h(3, "Описание доработок"),
            h(3, "Критерий приёмки"),
            h(1, "Ревью требований"),
        ]
    )
    result = validate_template("[СТ] GDS-15 Загрузка кино на витрину", body, SEED)
    assert not result.passed
    md = result.findings_markdown
    assert "Требования к интерфейсам" in md          # раздел отсутствует полностью
    assert "Документация по функционалу" in md      # нет в обоих блоках ФТ
    assert "Критерии приёмки" in md                 # «Критерий приёмки» не считается


def test_no_headings_fails():
    result = validate_template("[СТ] Пустой", "<p>Только текст без заголовков</p>", SEED)
    assert not result.passed


def test_heading_matches_prefix_and_exact():
    norm = normalize_heading("Функциональные требования (BackEnd)")
    assert heading_matches(norm, normalize_heading("Функциональные требования"))
    assert heading_matches(norm, normalize_heading("функциональные требования"))
    assert not heading_matches(norm, normalize_heading("Требования к интерфейсам"))
    # «Критерий приёмки» != «Критерии приёмки» — это разные заголовки
    assert not heading_matches(
        normalize_heading("Критерий приёмки"), normalize_heading("Критерии приёмки")
    )


def test_extract_headings_skips_empty():
    headings = extract_headings("<h1> </h1><h2>Текст</h2>")
    assert len(headings) == 1 and headings[0].text == "Текст"


def test_order_violation_is_warning_not_failure():
    body = GOOD_BODY.replace(h(1, "Ревью требований"), "")
    body = h(1, "Ревью требований") + body  # вынесен в начало
    result = validate_template("[СТ] Документ", body, SEED)
    assert result.warning_count >= 1
    assert result.passed  # порядок — предупреждение, не провал
