"""Очередь внимания на главной: сборка секций из выборок repository.

Секции фиксированы и приоритетны: документ попадает только в первую
подходящую (провал → устарел → ждёт оценки). Лимит строк в секции — 8,
total — полный счётчик («и ещё N» на фронте).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import repository
from app.models import (
    Analyst,
    ConfluenceDocument,
    Team,
    ValidationReport,
    ValidationStatus,
)
from app.schemas import DashboardItem, DashboardSection, DashboardOut
from app.usecase.ai_settings import get_ai_connection

SECTION_LIMIT = 8


def get_dashboard(db: Session, user=None) -> DashboardOut:
    return DashboardOut(
        sections=[
            _failed_section(db),
            _stale_section(db),
            _ratings_section(db),
            _no_team_section(db),
            _references_section(db, user),
        ],
        my_analysts=_my_analysts(db, user),
    )


def _my_analysts(db: Session, user) -> list:
    """Аналитики, которых курирует пользователь как лид: имя, команда,
    число документов и сколько из них сейчас в проблемных статусах."""
    from sqlalchemy import func, select

    from app.schemas import MyAnalystItem

    if user is None:
        return []
    analysts = list(
        db.scalars(
            select(Analyst)
            .where(Analyst.lead_user_id == user.id)
            .order_by(Analyst.full_name)
        ).all()
    )
    items = []
    for analyst in analysts:
        docs_count = db.scalar(
            select(func.count())
            .select_from(ConfluenceDocument)
            .where(ConfluenceDocument.analyst_id == analyst.id)
        ) or 0
        problem = db.scalar(
            select(func.count())
            .select_from(ConfluenceDocument)
            .where(
                ConfluenceDocument.analyst_id == analyst.id,
                ConfluenceDocument.validation_status.in_(
                    (ValidationStatus.FAILED, ValidationStatus.ERROR)
                ),
            )
        ) or 0
        team_name = None
        if analyst.team_id is not None:
            team = repository.org.get_team(db, analyst.team_id)
            team_name = team.name if team else None
        items.append(
            MyAnalystItem(
                key=f"analyst-{analyst.id}",
                analyst_id=analyst.id,
                name=analyst.full_name,
                team_name=team_name,
                documents_count=docs_count,
                validation_status=None,
            )
        )
        items[-1].__dict__["_problem"] = problem  # не в схеме: служебное
    return items


def _failed_section(db: Session) -> DashboardSection:
    rows = repository.dashboard.failed_docs(db, limit=SECTION_LIMIT)
    items = []
    for doc, report in rows:
        items.append(
            DashboardItem(
                key=f"doc-{doc.id}",
                title=doc.title,
                subtitle=_failed_subtitle(db, doc, report),
                at=report.created_at if report else doc.last_validated_at,
                document_id=doc.id,
            )
        )
    return DashboardSection(
        type="failed",
        title="Провалены проверки",
        total=repository.dashboard.failed_total(db),
        items=items,
    )


def _stale_section(db: Session) -> DashboardSection:
    rows = repository.dashboard.stale_docs(db, limit=SECTION_LIMIT)
    items = [
        DashboardItem(
            key=f"doc-{doc.id}",
            title=doc.title,
            subtitle=_doc_context(db, doc),
            at=modified,
            document_id=doc.id,
        )
        for doc, modified in rows
    ]
    return DashboardSection(
        type="stale",
        title="Устарели после правок в Confluence",
        total=repository.dashboard.stale_total(db),
        items=items,
    )


def _ratings_section(db: Session) -> DashboardSection:
    rows = repository.dashboard.awaiting_ratings(db, limit=SECTION_LIMIT)
    items = []
    for doc, report, _last_rated in rows:
        items.append(
            DashboardItem(
                key=f"doc-{doc.id}",
                title=doc.title,
                subtitle=f"{_doc_context(db, doc)} · прогон прошёл, оценок нет",
                at=report.created_at,
                document_id=doc.id,
            )
        )
    return DashboardSection(
        type="ratings",
        title="Ждут оценки руководителя",
        total=repository.dashboard.awaiting_ratings_total(db),
        items=items,
    )


def _no_team_section(db: Session) -> DashboardSection:
    rows = repository.dashboard.analysts_without_team(db, limit=SECTION_LIMIT)
    items = [
        DashboardItem(
            key=f"analyst-{analyst.id}",
            title=analyst.full_name,
            subtitle=f"{analyst.email} · {count} "
            + _plural(count, "документ", "документа", "документов"),
            analyst_id=analyst.id,
        )
        for analyst, count in rows
    ]
    return DashboardSection(
        type="no_team",
        title="Аналитики без команды",
        total=repository.dashboard.analysts_without_team_total(db),
        items=items,
    )


def _references_section(db: Session, user=None) -> DashboardSection:
    """Справочники в опасности: без них проверка работает неправильно."""
    items: list[DashboardItem] = []

    templates = repository.templates.list_not_archived(db)
    no_active = [
        template
        for template in templates
        if repository.templates.get_active_version(db, template) is None
    ]
    for template in no_active:
        # имя помнит последняя версия; у контейнера без версий — только номер
        versions = repository.templates.list_versions_desc(db, template.id)
        name = versions[0].name if versions else f"№{template.id}"
        items.append(
            DashboardItem(
                key=f"tpl-{template.id}",
                title=f"Шаблон «{name}» без активной версии",
                subtitle="не участвует в выборе при проверке — добавьте версию",
                template_id=template.id,
                section="templates",
            )
        )
    if templates and repository.templates.get_default(db) is None:
        items.append(
            DashboardItem(
                key="no-default-template",
                title="Не выбран шаблон «по умолчанию»",
                subtitle="диалог проверки останется без предвыбора — назначьте шаблон",
                section="templates",
            )
        )
    if not repository.criteria.list_active(db):
        items.append(
            DashboardItem(
                key="no-active-criteria",
                title="Нет активных ИИ-критериев",
                subtitle="ИИ-проверка уйдёт в ошибку — восстановите или добавьте критерий",
                section="criteria",
            )
        )
    connection = get_ai_connection(db, user)
    if connection is None or not (connection.base_url and connection.api_key):
        items.append(
            DashboardItem(
                key="no-ai-connection",
                title="Не настроено подключение к ИИ",
                subtitle="ИИ-проверки не смогут запуститься — укажите провайдера и токен",
                section="ai",
            )
        )
    # секция не ограничена выборкой — режем руками: схема допускает 8 строк
    return DashboardSection(
        type="references",
        title="Проблемы справочников",
        total=len(items),
        items=items[:SECTION_LIMIT],
    )


def _failed_subtitle(db: Session, doc: ConfluenceDocument, report: ValidationReport | None) -> str:
    if report is None:
        return _doc_context(db, doc)
    if report.error_message:
        return f"{_doc_context(db, doc)} · техническая ошибка — повторите проверку"
    template_failed = report.template_passed is False
    ai_failed = report.ai_passed is False
    if template_failed and ai_failed:
        reason = "шаблон и ИИ-проверка не пройдены"
    elif template_failed:
        reason = "не пройдена проверка по шаблону"
    else:
        reason = "ИИ-проверка: есть замечания"
    return f"{_doc_context(db, doc)} · {reason}"


def _doc_context(db: Session, doc: ConfluenceDocument) -> str:
    """«Алиев Рустам · GDS» — кто и где; для строк очереди этого достаточно."""
    analyst = repository.analysts.get(db, doc.analyst_id) if doc.analyst_id else None
    if analyst is None:
        return "?"
    parts = [analyst.full_name]
    if analyst.team_id is not None:
        team = repository.org.get_team(db, analyst.team_id)
        if team is not None:
            parts.append(team.name)
    return " · ".join(parts)


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many
