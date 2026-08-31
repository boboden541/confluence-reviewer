"""Конвертация storage-XHTML Confluence в Markdown для передачи в ИИ.

Задача — не пиксельная точность, а читаемый для LLM текст: заголовки,
абзацы, списки, таблицы, ссылки, код и макеты-панели (info/note/warning).
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString, Tag

# Ограничение входа модели (с запасом под контекст glm-4.5)
DEFAULT_MAX_CHARS = 100_000

_PANEL_NAMES = {"info": "ℹ️ Примечание", "note": "📝 Замечание",
                "warning": "⚠️ Внимание", "tip": "💡 Совет"}


def html_to_markdown(content_html: str, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Markdown-представление storage-формата страницы (для промпта ИИ)."""
    soup = BeautifulSoup(content_html or "", "lxml")
    root = soup.body if soup.body is not None else soup
    markdown = "".join(_render_node(child) for child in root.children)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()
    if not markdown:
        return ""
    if len(markdown) > max_chars:
        total = len(markdown)
        markdown = (
            markdown[:max_chars].rstrip()
            + f"\n\n[… документ обрезан: показаны первые {max_chars} символов из {total} …]"
        )
    return markdown


# --- inline-элементы ---


def _inline(tag: Tag) -> str:
    text = "".join(_render_node(child) for child in tag.children)
    return " ".join(text.split())


def _heading(tag: Tag) -> str:
    level = int(tag.name[1])
    return f"{'#' * level} {_inline(tag)}\n\n"


def _link(tag: Tag) -> str:
    label = _inline(tag)
    href = tag.get("href", "")
    return f"[{label}]({href})" if href else label


def _render_list(tag: Tag, ordered: bool, depth: int = 0) -> str:
    lines: list[str] = []
    index = 0
    for child in tag.find_all("li", recursive=False):
        index += 1
        marker = f"{index}. " if ordered else "- "
        # содержимое li: inline-часть + вложенные списки
        nested: list[str] = []
        inline_parts: list[str] = []
        for node in child.children:
            if isinstance(node, Tag) and node.name in {"ul", "ol"}:
                nested.append(_render_list(node, node.name == "ol", depth + 1))
            else:
                inline_parts.append(_render_node(node))
        bullet_text = " ".join("".join(inline_parts).split())
        lines.append(f"{'  ' * depth}{marker}{bullet_text}")
        lines.extend(nested)
    return "\n".join(lines) + "\n\n"


def _render_table(tag: Tag) -> str:
    rows: list[tuple[list[str], bool]] = []  # (ячейки, строка-заголовок)
    for tr in tag.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        rows.append(([_inline(c) for c in cells], bool(tr.find("th"))))

    lines: list[str] = []
    if not rows:
        return ""
    cells, is_header = rows[0]
    lines.append("| " + " | ".join(cells) + " |")
    if is_header:
        lines.append("|" + "---|" * len(cells))
    for cells, _ in rows[1:]:
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n\n"


def _render_panel(tag: Tag) -> str:
    name = (tag.get("ac:name") or "").lower()
    label = _PANEL_NAMES.get(name, name or "панель")
    body = "".join(_render_node(child) for child in tag.children
                   if not (isinstance(child, Tag) and child.name == "ac:parameter"))
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if not body:
        return ""
    return f"> **{label}**\n" + "\n".join(f"> {line}" for line in body.splitlines()) + "\n\n"


def _render_node(node) -> str:  # noqa: ANN001 — bs4-элементы
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""

    name = node.name
    if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return _heading(node)
    if name == "p":
        text = _inline(node)
        return f"{text}\n\n" if text else ""
    if name == "br":
        return "\n"
    if name == "hr":
        return "---\n\n"
    if name in {"strong", "b"}:
        inner = _inline(node)
        return f"**{inner}**" if inner else ""
    if name in {"em", "i", "u", "cite"}:
        inner = _inline(node)
        return f"*{inner}*" if inner else ""
    if name == "code":
        return f"`{_inline(node)}`"
    if name == "pre":
        return f"```\n{node.get_text().strip()}\n```\n\n"
    if name == "a":
        return _link(node)
    if name == "ac:link":
        return _inline(node)  # внутри обычно ri:page с заголовком целевой страницы
    if name == "ri:page":
        return str(node.get("ri:content-title") or "")
    if name == "ri:attachment":
        return f"[вложение: {node.get('ri:filename', '')}]"
    if name == "ac:image":
        return "[изображение]"
    if name in {"ul", "ol"}:
        return _render_list(node, name == "ol")
    if name == "table":
        return _render_table(node)
    if name == "blockquote":
        body = "".join(_render_node(c) for c in node.children).strip()
        return "\n".join(f"> {line}" for line in body.splitlines()) + "\n\n"
    if name == "ac:structured-macro":
        return _render_panel(node)
    if name == "ac:plain-text-body":
        return node.get_text().strip() + "\n\n"
    if name in {"ac:parameter", "style", "script"}:
        return ""  # служебное содержимое — мусор для модели
    # div/section/span и прочее — просто содержимое
    return "".join(_render_node(child) for child in node.children)
