"""Документы аналитиков: список, сортировка, пагинация, поиск (ФТ-CR-7..ФТ-CR-9)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.confluence import ConfluenceError
from app.database import get_db
from app.models import Analyst, ConfluenceDocument, DocumentNote, TriggerType
from app.schemas import (
    DocumentOut,
    DocumentPage,
    DocumentListItem,
    NoteOut,
    NoteUpdate,
    SearchHit,
    ValidationReportOut,
)
from app.services import tasks
from app.services.comments import (
    CommentError,
    NoReportError,
    publish_report_comment,
)
from app.services.semantic_search import SemanticSearchError, SemanticSearcher
from app.services.validation import DocumentNotFound, latest_report

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
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    """ФТ-CR-7: список документов от новых к старым, с пагинацией и поиском."""
    if db.get(Analyst, analyst_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Аналитик не найден")

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


@router.post(
    "/documents/{document_id}/validate",
    status_code=status.HTTP_202_ACCEPTED,
)
async def validate_document(
    document_id: int,
    db: Session = Depends(get_db),
    force: bool = Query(default=False, description="Перевалидировать безусловно"),
):
    """ФТ-CR-16: ручной запуск валидации (в фоне)."""
    get_document_or_404(document_id, db)
    started, message = tasks.start_validation(
        document_id, trigger=TriggerType.MANUAL, force=force
    )
    if not started:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return {"detail": message, "document_id": document_id}


@router.get("/documents/{document_id}/report", response_model=ValidationReportOut)
def get_report(document_id: int, db: Session = Depends(get_db)):
    """Последний отчёт валидации документа (ФТ-CR-13)."""
    get_document_or_404(document_id, db)
    report = latest_report(document_id)
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
        report = await publish_report_comment(document_id)
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
