"""Документы аналитиков: список, сортировка, пагинация, поиск (ФТ-CR-7..ФТ-CR-9).

Тонкий слой над usecase: парсинг входа, guard периодов и перевод доменных
исключений в HTTP-ответы с теми же кодами и текстами.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.clients.confluence import ConfluenceError
from app.clients.semantic_search import SemanticSearchError
from app.dependencies import get_db, require_permission, require_user
from app.dependencies.auth import resolve_actor
from app.schemas import (
    CriterionOptionOut,
    DocumentOut,
    DocumentPage,
    NoteOut,
    NoteUpdate,
    RatingsOut,
    RatingsUpdate,
    SearchHit,
    ValidationBatchRequest,
    ValidationConfigOut,
    ValidationOptions,
    ValidationReportOut,
)
from app.usecase import documents as documents_uc
from app.usecase import ratings, tasks
from app.clients.ai_validator import SYSTEM_PROMPT
from app.usecase.comments import (
    CommentError,
    NoReportError,
    publish_report_comment,
)
from app.usecase.criteria import (
    PROMPT_HEAD,
    PROMPT_TAIL,
    seed_criteria_if_missing,
    select_criteria,
)
from app.usecase.exceptions import AnalystNotFound, CriterionNotFound, DocumentNotFound
from app.usecase.templates import get_active_version, list_templates, seed_if_missing
from app.usecase.validation import (
    AI_CHECK,
    TEMPLATE_CHECK,
    latest_report,
    normalize_checks,
)
from app.models import TriggerType, User
from app.utils import normalize_period_end, to_naive_utc

router = APIRouter(prefix="/api", tags=["documents"])

_UNSET = object()  # валидация сама считает подключение, когда не передано


def _ai_connection_dep(
    db: Session = Depends(get_db), user: User | None = Depends(require_user)
):
    """Эффективное подключение ИИ текущего пользователя (None — не настроено)."""
    from app.usecase.ai_settings import get_ai_connection

    return get_ai_connection(db, resolve_actor(db, user))




def _get_document_or_404(db: Session, document_id: int):
    try:
        return documents_uc.get_document(db, document_id)
    except DocumentNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден") from exc


@router.get("/analysts/{analyst_id}/documents", response_model=DocumentPage)
def list_documents(
    analyst_id: int,
    db: Session = Depends(get_db),
    query: str | None = Query(default=None, max_length=512, description="Поиск по названию"),
    url: str | None = Query(default=None, max_length=1024, description="Поиск по ссылке"),
    created_from: datetime | None = Query(
        default=None, description="Создан в Confluence с даты (включительно)"
    ),
    created_to: datetime | None = Query(
        default=None, description="Создан в Confluence по дату (включительно)"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=documents_uc.DEFAULT_PAGE_SIZE, ge=1, le=documents_uc.MAX_PAGE_SIZE),
):
    """ФТ-CR-7: список документов от новых к старым, с пагинацией и поиском.

    Период created_from/created_to фильтрует по дате создания в Confluence,
    границы включительны (date-only «по» охватывает весь последний день).
    Документы без даты создания в период не попадают.
    """
    # aware-границы («Z», «+03:00») приводим к наивному UTC до guard и SQL:
    # иначе сравнение naive>aware даёт 500, а SQL теряет offset
    created_from = to_naive_utc(created_from)
    created_to = to_naive_utc(created_to)
    if (
        created_from is not None
        and created_to is not None
        and created_from > normalize_period_end(created_to)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Дата начала периода позже даты окончания",
        )
    try:
        return documents_uc.list_documents(
            db,
            analyst_id,
            query=query,
            url=url,
            created_from=created_from,
            created_to=normalize_period_end(created_to) if created_to is not None else None,
            page=page,
            page_size=page_size,
        )
    except AnalystNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Аналитик не найден") from exc


@router.get("/analysts/{analyst_id}/documents/semantic", response_model=DocumentPage)
def semantic_documents(
    analyst_id: int,
    db: Session = Depends(get_db),
    query: str = Query(min_length=2, max_length=512, description="Смысловое соответствие"),
    limit: int = Query(default=20, ge=1, le=50),
):
    """Семантический поиск: GLM ранжирует заголовки по смыслу запроса."""
    try:
        return documents_uc.semantic_documents(db, analyst_id, query, limit)
    except AnalystNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Аналитик не найден") from exc
    except SemanticSearchError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Семантический поиск недоступен: {exc}",
        )


@router.get("/documents/search", response_model=list[SearchHit])
def search_documents(
    db: Session = Depends(get_db),
    q: str = Query(default="", max_length=256, description="Подстрока названия документа"),
    limit: int = Query(default=8, ge=1, le=25),
):
    """Глобальный поиск по названию — документы всех аналитиков (шапка сервиса)."""
    return documents_uc.global_search(db, q, limit)


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, db: Session = Depends(get_db)):
    """Объект документа (страница просмотра отчёта)."""
    try:
        return documents_uc.get_document_card(db, document_id)
    except DocumentNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден") from exc


@router.get("/validation-config", response_model=ValidationConfigOut)
def get_validation_config(
    db: Session = Depends(get_db), user: User | None = Depends(require_user)
):
    """Конфиг диалога проверки: шаблоны, ИИ-критерии и части собранного промта.

    Шаблоны — неархивные с активными версиями («по умолчанию» первым); id
    элемента = номер активной версии, он уходит в проверку как template_id.
    Критерии отдаются только активные: галочки диалога и блоки собранного промта.
    """
    actor = resolve_actor(db, user)
    seed_if_missing(db, owner_user_id=actor.id)
    seed_criteria_if_missing(db, owner_user_id=actor.id)
    templates = []
    for template in list_templates(db, owner_user_id=actor.id):
        if template.archived_at is not None:
            continue
        version = get_active_version(db, template)
        if version is None:
            continue
        templates.append(
            {
                "id": version.id,
                "name": version.name,
                "description": version.description,
                "is_default": template.is_default,
                "section_count": len(json.loads(version.sections_json)),
            }
        )
    criteria = [
        CriterionOptionOut(id=c.id, code=c.code, name=c.name, prompt=c.prompt)
        for c in select_criteria(db, owner_user_id=actor.id)
    ]
    return ValidationConfigOut(
        templates=templates,
        default_prompt=SYSTEM_PROMPT,
        criteria=criteria,
        prompt_head=PROMPT_HEAD,
        prompt_tail=PROMPT_TAIL,
    )


@router.post(
    "/documents/{document_id}/validate",
    status_code=status.HTTP_202_ACCEPTED,
)
async def validate_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_permission("checks")),
    force: bool = Query(default=False, description="Перевалидировать безусловно"),
    options: ValidationOptions | None = None,
    ai_connection=Depends(_ai_connection_dep),
):
    """ФТ-CR-16: ручной запуск валидации (в фоне).

    Тело (опционально) — настройки из диалога проверки: критерии checks,
    template_id, ai_prompt и criterion_ids (ИИ-критерии запуска).
    """
    actor = resolve_actor(db, user)
    _get_document_or_404(db, document_id)
    checks = options.checks if options else None
    # существование версии проверяем, только если шаблонная проверка запрошена
    if TEMPLATE_CHECK in normalize_checks(checks):
        _check_template_exists(options.template_id if options else None, db)
    # критерии ИИ — только при запущенной ИИ-проверке
    if AI_CHECK in normalize_checks(checks):
        _check_criteria_usable(db, options.criterion_ids if options else None, actor)
        if ai_connection is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Настройте личный доступ к ИИ (раздел «Мой доступ к ИИ»), "
                "чтобы запускать ИИ-проверку",
            )
    started, message = tasks.start_validation(
        document_id,
        trigger=TriggerType.MANUAL,
        force=force,
        template_version_id=options.template_id if options else None,
        ai_prompt=options.ai_prompt if options else None,
        checks=checks,
        criterion_ids=options.criterion_ids if options else None,
        ai_connection=ai_connection if ai_connection is not None else _UNSET,
        owner_user=actor,
        actor_user=actor,
    )
    if not started:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return {"detail": message, "document_id": document_id}


def _check_criteria_usable(db: Session, criterion_ids: list[int] | None, actor) -> None:
    """Выбранные ИИ-критерии владельца должны существовать и быть активными."""
    if criterion_ids is None:
        return
    try:
        select_criteria(db, criterion_ids, owner_user_id=actor.id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _check_template_exists(template_id: int | None, db: Session) -> None:
    """Выбранная версия шаблона должна существовать (задел на несколько шаблонов)."""
    if template_id is not None and not documents_uc.template_version_exists(db, template_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Шаблон (версия {template_id}) не найден",
        )


@router.post("/documents/validate-batch", status_code=status.HTTP_202_ACCEPTED)
async def validate_documents_batch(
    payload: ValidationBatchRequest,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_permission("checks")),
    ai_connection=Depends(_ai_connection_dep),
):
    """Проверка выбранных документов (в фоне, последовательно).

    Не-force: актуальные документы пропускаются идемпотентностью;
    изменённый промт ИИ (override или правка критерия) сам по себе
    принуждает к перепроверке — сравнением хэша промта.
    """
    actor = resolve_actor(db, user)
    # существование версии проверяем, только если шаблонная проверка запрошена
    if TEMPLATE_CHECK in normalize_checks(payload.checks):
        _check_template_exists(payload.template_id, db)
    if AI_CHECK in normalize_checks(payload.checks):
        _check_criteria_usable(db, payload.criterion_ids, actor)
    missing = documents_uc.missing_document_ids(db, payload.document_ids)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Документы не найдены: {', '.join(map(str, missing))}",
        )
    # порядок = порядок выбора, дубликаты не проверяем дважды
    doc_ids = list(dict.fromkeys(payload.document_ids))
    if AI_CHECK in normalize_checks(payload.checks) and ai_connection is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Настройте личный доступ к ИИ (раздел «Мой доступ к ИИ»), "
            "чтобы запускать ИИ-проверку",
        )
    started, message = tasks.start_bulk_validation(
        doc_ids,
        force=payload.force,
        template_version_id=payload.template_id,
        ai_prompt=payload.ai_prompt,
        checks=payload.checks,
        criterion_ids=payload.criterion_ids,
        ai_connection=ai_connection if ai_connection is not None else _UNSET,
        owner_user=actor,
        actor_user=actor,
    )
    if not started:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return {"status": "started", "message": message, "total": len(doc_ids)}


@router.get("/documents/{document_id}/report", response_model=ValidationReportOut)
def get_report(document_id: int, db: Session = Depends(get_db)):
    """Последний отчёт валидации документа (ФТ-CR-13)."""
    _get_document_or_404(db, document_id)
    report = latest_report(db, document_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Отчёт валидации ещё не сформирован",
        )
    return ValidationReportOut.model_validate(report)


@router.post("/documents/{document_id}/comment", response_model=ValidationReportOut)
async def post_comment(
    document_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_permission("comments")),
):
    """ФТ-CR-17: опубликовать замечания отчёта комментарием на страницу Confluence."""
    _get_document_or_404(db, document_id)
    try:
        report = await publish_report_comment(db, document_id)
    except (DocumentNotFound, NoReportError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Отчёт валидации ещё не сформирован",
        )
    except CommentError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ConfluenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Не удалось опубликовать комментарий: {exc}",
        )
    return ValidationReportOut.model_validate(report)


@router.get("/documents/{document_id}/ratings", response_model=RatingsOut)
def get_ratings(
    document_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    """Блок оценивания: мои активные критерии с моими оценками этого документа.

    Виден до первого ИИ-прогона; пустой criteria — в справочнике
    нет активных критериев.
    """
    _get_document_or_404(db, document_id)
    return ratings.get_ratings_view(db, document_id, owner_user=user)


@router.put("/documents/{document_id}/ratings", response_model=RatingsOut)
def update_ratings(
    document_id: int,
    payload: RatingsUpdate,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    """Выставить/изменить оценки (1..10); score=None — снять («—»).

    Оценивать можно только свои критерии; архивный или чужой — 404.
    """
    _get_document_or_404(db, document_id)
    try:
        return ratings.apply_ratings(db, document_id, payload.ratings, owner_user=user)
    except CriterionNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/documents/{document_id}/note", response_model=NoteOut)
def get_note(document_id: int, db: Session = Depends(get_db)):
    """Заметка руководителя по документу (ФТ-CR-18); пустая, если ещё не было."""
    _get_document_or_404(db, document_id)
    return documents_uc.get_note_view(db, document_id)


@router.put("/documents/{document_id}/note", response_model=NoteOut)
def update_note(document_id: int, payload: NoteUpdate, db: Session = Depends(get_db)):
    """Создать или перезаписать заметку (Markdown, одна на документ)."""
    _get_document_or_404(db, document_id)
    return documents_uc.save_note(db, document_id, payload.content)


@router.delete("/documents/{document_id}/note", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(document_id: int, db: Session = Depends(get_db)):
    """Удалить заметку документа. Идемпотентно: заметки нет — тоже 204."""
    _get_document_or_404(db, document_id)
    documents_uc.delete_note(db, document_id)
