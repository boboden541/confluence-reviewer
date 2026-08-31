"""Документы аналитиков: список, сортировка, пагинация, поиск (ФТ-CR-7..ФТ-CR-9)."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clients.confluence import ConfluenceError
from app.dependencies import get_db
from app.models import Analyst, ConfluenceDocument, DocumentNote, TemplateVersion, TriggerType
from app.schemas import (
    CriterionOptionOut,
    DocumentOut,
    DocumentPage,
    DocumentListItem,
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
from app.services import tasks
from app.usecase import ratings
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
from app.usecase.exceptions import CriterionNotFound
from app.clients.semantic_search import SemanticSearchError, SemanticSearcher
from app.usecase.templates import get_active_version, list_templates, seed_if_missing
from app.usecase.validation import (
    AI_CHECK,
    DocumentNotFound,
    TEMPLATE_CHECK,
    latest_report,
    normalize_checks,
)
from app.utils import normalize_period_end, to_naive_utc

router = APIRouter(prefix="/api", tags=["documents"])

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20

# один экземпляр на процесс: кэш результатов семантического поиска живёт в нём
searcher = SemanticSearcher()


def get_document_or_404(document_id: int, db: Session) -> ConfluenceDocument:
    doc = db.get(ConfluenceDocument, document_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")
    return doc


def _normalize_url(value: str) -> str:
    """Поиск по ссылке: игнорируем хвостовой слэш и протокол."""
    value = value.strip().rstrip("/")
    for prefix in ("https://", "http://"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    return value.rstrip("/")


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
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    """ФТ-CR-7: список документов от новых к старым, с пагинацией и поиском.

    Период created_from/created_to фильтрует по дате создания в Confluence,
    границы включительны (date-only «по» охватывает весь последний день).
    Документы без даты создания в период не попадают.
    """
    if db.get(Analyst, analyst_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Аналитик не найден")
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

    conditions = [ConfluenceDocument.analyst_id == analyst_id]
    if query and query.strip():
        # lower() с обеих сторон: sqlite ILIKE не сворачивает регистр кириллицы
        conditions.append(
            func.lower(ConfluenceDocument.title).like(f"%{query.strip().lower()}%")
        )
    if url and url.strip():
        conditions.append(
            func.lower(ConfluenceDocument.url).like(f"%{_normalize_url(url).lower()}%")
        )
    if created_from is not None:
        conditions.append(ConfluenceDocument.created_in_confluence_at >= created_from)
    if created_to is not None:
        conditions.append(
            ConfluenceDocument.created_in_confluence_at <= normalize_period_end(created_to)
        )

    total = db.scalar(select(func.count()).select_from(ConfluenceDocument).where(*conditions)) or 0

    items = db.scalars(
        select(ConfluenceDocument)
        .where(*conditions)
        .order_by(
            ConfluenceDocument.created_in_confluence_at.desc().nullslast(),
            ConfluenceDocument.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    # у каких документов страницы есть заметки — одним запросом
    noted_ids: set[int] = set()
    if items:
        noted_ids = set(
            db.scalars(
                select(DocumentNote.document_id).where(
                    DocumentNote.document_id.in_([item.id for item in items])
                )
            ).all()
        )

    return DocumentPage(
        items=[
            _to_list_item(item, item.id in noted_ids) for item in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


def _to_list_item(item: ConfluenceDocument, has_note: bool) -> DocumentListItem:
    out = DocumentListItem.model_validate(item)
    out.has_note = has_note
    return out


@router.get("/analysts/{analyst_id}/documents/semantic", response_model=DocumentPage)
def semantic_documents(
    analyst_id: int,
    db: Session = Depends(get_db),
    query: str = Query(min_length=2, max_length=512, description="Смысловое соответствие"),
    limit: int = Query(default=20, ge=1, le=50),
):
    """Семантический поиск: GLM ранжирует заголовки по смыслу запроса."""
    if db.get(Analyst, analyst_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Аналитик не найден")

    rows = db.execute(
        select(ConfluenceDocument.id, ConfluenceDocument.title)
        .where(ConfluenceDocument.analyst_id == analyst_id)
        .order_by(ConfluenceDocument.id)
    ).all()
    if not rows:
        return DocumentPage(items=[], total=0, page=1, page_size=limit)

    try:
        matches = searcher.search(analyst_id, query.strip(), list(rows))
    except SemanticSearchError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Семантический поиск недоступен: {exc}",
        )

    docs = {
        doc.id: doc
        for doc in db.scalars(
            select(ConfluenceDocument).where(
                ConfluenceDocument.id.in_([doc_id for doc_id, _ in matches])
            )
        ).all()
    }
    noted_ids: set[int] = set()
    if matches:
        noted_ids = set(
            db.scalars(
                select(DocumentNote.document_id).where(
                    DocumentNote.document_id.in_([doc_id for doc_id, _ in matches])
                )
            ).all()
        )

    items: list[DocumentListItem] = []
    for doc_id, score in matches[:limit]:
        item = _to_list_item(docs[doc_id], doc_id in noted_ids)
        item.score = round(score, 3)
        items.append(item)
    return DocumentPage(items=items, total=len(items), page=1, page_size=limit)


@router.get("/documents/search", response_model=list[SearchHit])
def search_documents(
    db: Session = Depends(get_db),
    q: str = Query(default="", max_length=256, description="Подстрока названия документа"),
    limit: int = Query(default=8, ge=1, le=25),
):
    """Глобальный поиск по названию — документы всех аналитиков (шапка сервиса)."""
    needle = q.strip().lower()
    if len(needle) < 2:
        return []
    rows = db.execute(
        select(ConfluenceDocument, Analyst.full_name)
        .join(Analyst, ConfluenceDocument.analyst_id == Analyst.id)
        .where(func.lower(ConfluenceDocument.title).like(f"%{needle}%"))
        .order_by(
            ConfluenceDocument.last_modified_in_confluence_at.desc().nullslast(),
            ConfluenceDocument.id.desc(),
        )
        .limit(limit)
    ).all()
    return [
        SearchHit(
            id=doc.id,
            title=doc.title,
            validation_status=doc.validation_status,
            analyst_id=doc.analyst_id,
            analyst_name=analyst_name,
        )
        for doc, analyst_name in rows
    ]


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, db: Session = Depends(get_db)):
    """Объект документа (страница просмотра отчёта)."""
    doc = get_document_or_404(document_id, db)
    analyst = db.get(Analyst, doc.analyst_id)
    out = DocumentOut.model_validate(doc)
    # автор — из карточки аналитика; «?» если карточку удалили, а документы остались
    out.analyst_name = analyst.full_name if analyst else "?"
    out.analyst_email = analyst.email if analyst else None
    return out


@router.get("/validation-config", response_model=ValidationConfigOut)
def get_validation_config(db: Session = Depends(get_db)):
    """Конфиг диалога проверки: шаблоны, ИИ-критерии и части собранного промта.

    Шаблоны — неархивные с активными версиями («по умолчанию» первым); id
    элемента = номер активной версии, он уходит в проверку как template_id.
    Критерии отдаются только активные: галочки диалога и блоки собранного промта.
    """
    seed_if_missing(db)
    seed_criteria_if_missing(db)
    templates = []
    for template in list_templates(db):
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
        for c in select_criteria(db)
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
    force: bool = Query(default=False, description="Перевалидировать безусловно"),
    options: ValidationOptions | None = None,
):
    """ФТ-CR-16: ручной запуск валидации (в фоне).

    Тело (опционально) — настройки из диалога проверки: критерии checks,
    template_id, ai_prompt и criterion_ids (ИИ-критерии запуска).
    """
    get_document_or_404(document_id, db)
    checks = options.checks if options else None
    # существование версии проверяем, только если шаблонная проверка запрошена
    if TEMPLATE_CHECK in normalize_checks(checks):
        _check_template_exists(options.template_id if options else None, db)
    # критерии ИИ — только при запущенной ИИ-проверке
    if AI_CHECK in normalize_checks(checks):
        _check_criteria_usable(options.criterion_ids if options else None, db)
    started, message = tasks.start_validation(
        document_id,
        trigger=TriggerType.MANUAL,
        force=force,
        template_version_id=options.template_id if options else None,
        ai_prompt=options.ai_prompt if options else None,
        checks=checks,
        criterion_ids=options.criterion_ids if options else None,
    )
    if not started:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return {"detail": message, "document_id": document_id}


def _check_criteria_usable(criterion_ids: list[int] | None, db: Session) -> None:
    """Выбранные ИИ-критерии должны существовать и быть активными: молча
    вычеркнуть нельзя — промт запуска незаметно изменился бы."""
    if criterion_ids is None:
        return
    try:
        select_criteria(db, criterion_ids)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _check_template_exists(template_id: int | None, db: Session) -> None:
    """Выбранная версия шаблона должна существовать (задел на несколько шаблонов)."""
    if template_id is not None and db.get(TemplateVersion, template_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Шаблон (версия {template_id}) не найден",
        )


@router.post("/documents/validate-batch", status_code=status.HTTP_202_ACCEPTED)
async def validate_documents_batch(payload: ValidationBatchRequest, db: Session = Depends(get_db)):
    """Проверка выбранных документов (в фоне, последовательно).

    Не-force: актуальные документы пропускаются идемпотентностью;
    изменённый промт ИИ (override или правка критерия) сам по себе
    принуждает к перепроверке — сравнением хэша промта.
    """
    # существование версии проверяем, только если шаблонная проверка запрошена
    if TEMPLATE_CHECK in normalize_checks(payload.checks):
        _check_template_exists(payload.template_id, db)
    if AI_CHECK in normalize_checks(payload.checks):
        _check_criteria_usable(payload.criterion_ids, db)
    found = set(
        db.scalars(
            select(ConfluenceDocument.id).where(ConfluenceDocument.id.in_(payload.document_ids))
        ).all()
    )
    missing = sorted(set(payload.document_ids) - found)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Документы не найдены: {', '.join(map(str, missing))}",
        )
    # порядок = порядок выбора, дубликаты не проверяем дважды
    doc_ids = list(dict.fromkeys(payload.document_ids))
    started, message = tasks.start_bulk_validation(
        doc_ids,
        force=payload.force,
        template_version_id=payload.template_id,
        ai_prompt=payload.ai_prompt,
        checks=payload.checks,
        criterion_ids=payload.criterion_ids,
    )
    if not started:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return {"status": "started", "message": message, "total": len(doc_ids)}


@router.get("/documents/{document_id}/report", response_model=ValidationReportOut)
def get_report(document_id: int, db: Session = Depends(get_db)):
    """Последний отчёт валидации документа (ФТ-CR-13)."""
    get_document_or_404(document_id, db)
    report = latest_report(db, document_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Отчёт валидации ещё не сформирован",
        )
    return ValidationReportOut.model_validate(report)


@router.post("/documents/{document_id}/comment", response_model=ValidationReportOut)
async def post_comment(document_id: int, db: Session = Depends(get_db)):
    """ФТ-CR-17: опубликовать замечания отчёта комментарием на страницу Confluence."""
    get_document_or_404(document_id, db)
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


def _get_note(db: Session, document_id: int) -> DocumentNote | None:
    return db.scalar(
        select(DocumentNote).where(DocumentNote.document_id == document_id)
    )


@router.get("/documents/{document_id}/ratings", response_model=RatingsOut)
def get_ratings(document_id: int, db: Session = Depends(get_db)):
    """Блок оценивания: все активные критерии справочника с оценками руководителя.

    Виден до первого ИИ-прогона; пустой criteria — в справочнике
    нет активных критериев.
    """
    get_document_or_404(document_id, db)
    return ratings.get_ratings_view(db, document_id)


@router.put("/documents/{document_id}/ratings", response_model=RatingsOut)
def update_ratings(document_id: int, payload: RatingsUpdate, db: Session = Depends(get_db)):
    """Выставить/изменить оценки (1..10); score=None — снять («—»).

    Архивный или несуществующий критерий — 404 (молча вычеркнуть нельзя).
    """
    get_document_or_404(document_id, db)
    try:
        return ratings.apply_ratings(db, document_id, payload.ratings)
    except CriterionNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/documents/{document_id}/note", response_model=NoteOut)
def get_note(document_id: int, db: Session = Depends(get_db)):
    """Заметка руководителя по документу (ФТ-CR-18); пустая, если ещё не было."""
    get_document_or_404(document_id, db)
    note = _get_note(db, document_id)
    if note is None:
        return NoteOut(document_id=document_id, content="")
    return NoteOut.model_validate(note)


@router.put("/documents/{document_id}/note", response_model=NoteOut)
def update_note(document_id: int, payload: NoteUpdate, db: Session = Depends(get_db)):
    """Создать или перезаписать заметку (Markdown, одна на документ)."""
    get_document_or_404(document_id, db)
    note = _get_note(db, document_id)
    if note is None:
        note = DocumentNote(document_id=document_id, content=payload.content)
        db.add(note)
    else:
        note.content = payload.content
    db.commit()
    db.refresh(note)
    return NoteOut.model_validate(note)


@router.delete("/documents/{document_id}/note", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(document_id: int, db: Session = Depends(get_db)):
    """Удалить заметку документа. Идемпотентно: заметки нет — тоже 204."""
    get_document_or_404(document_id, db)
    note = _get_note(db, document_id)
    if note is not None:
        db.delete(note)
        db.commit()
