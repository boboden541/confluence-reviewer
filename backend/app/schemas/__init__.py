"""Pydantic-схемы API.

Пакет разбит по доменам (analysts / documents / validation / templates / ai /
ratings / org); фасад сохраняет контракт `from app.schemas import ...` —
потребители (роутеры, сервисы, тесты) продолжают импортировать классы
с одного места.
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
    AnalystLeadUpdate,
    AnalystCreate,
    AnalystDomainsUpdate,
    AnalystNoteOut,
    AnalystNoteUpdate,
    AnalystOut,
    AnalystUpdate,
)
from app.schemas.dashboard import (
    DashboardItem,
    MyAnalystItem,
    DashboardOut,
    DashboardSection,
    FeedItem,
)
from app.schemas.reminders import (
    ReminderCreate,
    ReminderOut,
)
from app.schemas.documents import (
    DocumentListItem,
    DocumentOut,
    DocumentPage,
    NoteOut,
    NoteUpdate,
    SearchHit,
)
from app.schemas.org import (
    AnalystBrief,
    ClusterCreate,
    ClusterOut,
    ClusterUpdate,
    TeamAnalystAdd,
    TeamBrief,
    TeamCreate,
    TeamOut,
    TeamUpdate,
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
    "AnalystBrief",
    "AnalystCreate",
    "AnalystLeadUpdate",
    "DashboardItem",
    "DashboardOut",
    "DashboardSection",
    "FeedItem",
    "MyAnalystItem",
    "AnalystDomainsUpdate",
    "AnalystNoteOut",
    "AnalystNoteUpdate",
    "AnalystOut",
    "AnalystUpdate",
    "CheckName",
    "ClusterCreate",
    "ClusterOut",
    "ClusterUpdate",
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
    "TeamAnalystAdd",
    "TeamBrief",
    "TeamCreate",
    "TeamOut",
    "TeamUpdate",
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
