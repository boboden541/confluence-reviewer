"""Тесты конвертации storage-XHTML в Markdown (вход для ИИ-валидации)."""

from __future__ import annotations

from app.services.html_to_markdown import html_to_markdown


def test_headings_and_inline_markup():
    md = html_to_markdown("<h1>Введение</h1><h2>Общая информация</h2><p>Текст <b>жирный</b> и <i>курсив</i></p>")
    assert "# Введение" in md
    assert "## Общая информация" in md
    assert "**жирный**" in md
    assert "*курсив*" in md


def test_nested_unordered_list():
    html = "<ul><li>первый<ul><li>вложенный</li></ul></li><li>второй</li></ul>"
    md = html_to_markdown(html)
    lines = [line for line in md.splitlines() if line.strip()]
    assert lines[0] == "- первый"
    assert lines[1] == "  - вложенный"
    assert lines[2] == "- второй"


def test_ordered_list():
    md = html_to_markdown("<ol><li>раз</li><li>два</li></ol>")
    assert "1. раз" in md
    assert "2. два" in md


def test_table_with_header():
    html = (
        "<table><tr><th>Колонка</th><th>Значение</th></tr>"
        "<tr><td>a</td><td>1</td></tr></table>"
    )
    md = html_to_markdown(html)
    assert "| Колонка | Значение |" in md
    assert "|---|---|" in md
    assert "| a | 1 |" in md


def test_link():
    md = html_to_markdown('<p><a href="https://x.test">ссылка</a></p>')
    assert "[ссылка](https://x.test)" in md


def test_code_block():
    md = html_to_markdown("<pre>SELECT 1</pre>")
    assert "```\nSELECT 1\n```" in md


def test_confluence_info_panel():
    html = (
        '<ac:structured-macro ac:name="info">'
        "<ac:rich-text-body><p>Важно</p></ac:rich-text-body>"
        "</ac:structured-macro>"
    )
    md = html_to_markdown(html)
    assert "> **ℹ️ Примечание**" in md
    assert "> Важно" in md


def test_confluence_page_link_uses_title():
    html = '<p>См. <ac:link><ri:page ri:content-title="GDS-15" /></ac:link></p>'
    md = html_to_markdown(html)
    assert "GDS-15" in md


def test_parameters_and_scripts_are_dropped():
    html = (
        '<ac:structured-macro ac:name="expand">'
        '<ac:parameter ac:name="foo">bar</ac:parameter>'
        "<ac:rich-text-body><p>Содержимое</p></ac:rich-text-body>"
        "</ac:structured-macro><style>.x{color:red}</style>"
    )
    md = html_to_markdown(html)
    assert "Содержимое" in md
    assert "bar" not in md
    assert "color" not in md


def test_empty_input():
    assert html_to_markdown("") == ""
    assert html_to_markdown(None) == ""  # type: ignore[arg-type]


def test_truncation_note():
    html = "<p>" + "x" * 20_000 + "</p>"
    md = html_to_markdown(html, max_chars=1000)
    assert len(md) < 1200
    assert "обрезан" in md
