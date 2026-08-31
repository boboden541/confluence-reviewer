"""Доменные исключения бизнес-логики.

Иерархии сознательно простые (LookupError/RuntimeError): существующие
`except LookupError` в потребителях продолжают ловить подклассы. api
переводит их в HTTPException с человекочитаемым detail; транспортные
ошибки внешних систем живут у клиентов (ConfluenceError, AIValidationError,
SemanticSearchError).
"""

from __future__ import annotations


class AnalystNotFound(LookupError):
    """Аналитик с таким id не существует."""


class DocumentNotFound(LookupError):
    """Документ с таким id не существует."""


class TemplateNotFound(LookupError):
    """Шаблон с таким id не существует."""


class TemplateHasNoActiveVersion(LookupError):
    """У шаблона нет активной версии (нет данных для редактора/проверки)."""


class CriterionNotFound(LookupError):
    """Критерий из запроса не существует."""


class CriterionSelectionError(LookupError):
    """Набор критериев прогона невалиден: id нет в БД или критерий в архиве."""


class NoReportError(LookupError):
    """У документа ещё нет отчёта валидации."""


class CommentError(RuntimeError):
    """Не удалось опубликовать комментарий в Confluence."""


class AnalystEmailTaken(RuntimeError):
    """Аналитик с таким email уже существует (конфликт создания/правки)."""
