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
    ValidationReportOut,
)
from app.services import tasks
from app.services.comments import (
    CommentError,
    NoReportError,
    publish_report_comment,
)
from app.services.validation import DocumentNotFound, latest_report

router = APIRouter(prefix="/api", tags=["documents"])

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


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

    return DocumentPage(
        items=[DocumentListItem.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, db: Session = Depends(get_db)):
    """Объект документа (страница просмотра отчёта)."""
    return DocumentOut.model_validate(get_document_or_404(document_id, db))


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
