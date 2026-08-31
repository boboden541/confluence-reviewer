"""Pydantic-схемы API.

Пакет разбит по доменам (analysts / documents / validation / templates / ai /
ratings); фасад сохраняет контракт `from app.schemas import ...` — потребители
(роутеры, сервисы, тесты) продолжают импортировать классы с одного места.
"""

from app.schemas.ai import (
    AIConnectionOut,
    AIConnectionTestRequest,
    AIConnectionTestResult,
    AIConnectionUpdate,
    AIEnvInfo,
    AiCriterionCreate,
    AiCriterionOut,
    AiCriterionUpdate,
)
from app.schemas.analysts import (
    AnalystCreate,
    AnalystNoteOut,
    AnalystNoteUpdate,
    AnalystOut,
    AnalystUpdate,
)
from app.schemas.documents import (
    DocumentListItem,
    DocumentOut,
    DocumentPage,
    NoteOut,
    NoteUpdate,
    SearchHit,
)
from app.schemas.ratings import (
    CriterionSummaryOut,
    RatingItem,
    RatingItemOut,
    RatingsOut,
    RatingsSummaryOut,
    RatingsUpdate,
)
from app.schemas.templates import (
    TemplateCardOut,
    TemplateOut,
    TemplateSave,
    TemplateSection,
    TemplateUpdate,
    TemplateVersionInfo,
)
from app.schemas.validation import (
    CheckName,
    CriterionOptionOut,
    TemplateOptionOut,
    ValidationBatchRequest,
    ValidationConfigOut,
    ValidationOptions,
    ValidationReportOut,
)

__all__ = [
    "AIConnectionOut",
    "AIConnectionTestRequest",
    "AIConnectionTestResult",
    "AIConnectionUpdate",
    "AIEnvInfo",
    "AiCriterionCreate",
    "AiCriterionOut",
    "AiCriterionUpdate",
    "AnalystCreate",
    "AnalystNoteOut",
    "AnalystNoteUpdate",
    "AnalystOut",
    "AnalystUpdate",
    "CheckName",
    "CriterionOptionOut",
    "CriterionSummaryOut",
    "DocumentListItem",
    "DocumentOut",
    "DocumentPage",
    "NoteOut",
    "NoteUpdate",
    "RatingItem",
    "RatingItemOut",
    "RatingsOut",
    "RatingsSummaryOut",
    "RatingsUpdate",
    "SearchHit",
    "TemplateCardOut",
    "TemplateOptionOut",
    "TemplateOut",
    "TemplateSave",
    "TemplateSection",
    "TemplateUpdate",
    "TemplateVersionInfo",
    "ValidationBatchRequest",
    "ValidationConfigOut",
    "ValidationOptions",
    "ValidationReportOut",
]
