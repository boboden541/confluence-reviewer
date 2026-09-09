"""Модель данных: аналитики, Confluence-документы, отчёты валидации, заметки,
версии шаблона требований, организационная структура.

Пакет разбит по доменам (analysts / documents / validation / templates / ai /
org); этот фасад собирает все ORM-классы и enum'ы вместе: мапперы SQLAlchemy
конфигурируются при импорте всех подмодулей, а потребители продолжают
писать `from app.models import Analyst`.

Время везде — наивный UTC (см. app.utils.now_utc), чтобы сравнения дат
(ФТ-CR-14) работали одинаково на sqlite и postgres.
"""

from app.models.ai import AIConnectionSettings, AiCriterion, CriterionRating
from app.models.analysts import Analyst, AnalystNote
from app.models.auth import AuthSession, RegistrationRequest, Role, User
from app.models.documents import ConfluenceDocument, DocumentNote
from app.models.org import Cluster, Team
from app.models.reminders import Reminder
from app.models.templates import Template, TemplateVersion
from app.models.validation import TriggerType, ValidationReport, ValidationStatus

__all__ = [
    "AIConnectionSettings",
    "AiCriterion",
    "Analyst",
    "AnalystNote",
    "AuthSession",
    "Cluster",
    "ConfluenceDocument",
    "CriterionRating",
    "DocumentNote",
    "Reminder",
    "RegistrationRequest",
    "Role",
    "Team",
    "Template",
    "TemplateVersion",
    "TriggerType",
    "User",
    "ValidationReport",
    "ValidationStatus",
]
