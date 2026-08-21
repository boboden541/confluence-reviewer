"""Документы аналитиков: список, сортировка, пагинация, поиск (ФТ-CR-7..ФТ-CR-9)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Analyst, ConfluenceDocument, TriggerType
from app.schemas import DocumentOut, DocumentPage, DocumentListItem, ValidationReportOut
from app.services import tasks
from app.services.validation import latest_report

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
