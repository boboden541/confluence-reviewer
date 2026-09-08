"""Документы аналитиков: список, поиск, карточка, заметки (ФТ-CR-7..ФТ-CR-9,
ФТ-CR-18).

Слой собирает выборки repository в схемы API и владеет записью заметок.
Семантический поиск держит один экземпляр ранжировщика на процесс — кэш
результатов живёт в нём.
"""

from __future__ import annotations

from app import repository
from app.clients.semantic_search import SemanticSearcher
from app.models import ConfluenceDocument, DocumentNote
from app.schemas import DocumentListItem, DocumentOut, DocumentPage, NoteOut, SearchHit
from app.usecase.exceptions import AnalystNotFound, DocumentNotFound

# один экземпляр на процесс: кэш результатов семантического поиска живёт в нём
searcher = SemanticSearcher()

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


def get_document(db, document_id: int) -> ConfluenceDocument:
    """Документ по id или DocumentNotFound (api переводит в 404)."""
    doc = db.get(ConfluenceDocument, document_id)
    if doc is None:
        raise DocumentNotFound(f"Документ {document_id} не найден")
    return doc


def _normalize_url(value: str) -> str:
    """Поиск по ссылке: игнорируем хвостовой слэш и протокол."""
    value = value.strip().rstrip("/")
    for prefix in ("https://", "http://"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    return value.rstrip("/")


def _to_list_item(item: ConfluenceDocument, has_note: bool) -> DocumentListItem:
    out = DocumentListItem.model_validate(item)
    out.has_note = has_note
    return out


def list_documents(
    db,
    analyst_id: int,
    *,
    query: str | None = None,
    url: str | None = None,
    created_from=None,
    created_to=None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> DocumentPage:
    """ФТ-CR-7: список документов от новых к старым, с пагинацией и поиском.

    Период created_from/created_to фильтрует по дате создания в Confluence,
    границы включительны (date-only «по» охватывает весь последний день).
    Документы без даты создания в период не попадают. Даты приходят уже
    наивными UTC (api привёл aware-границы до guard'а и SQL).
    """
    if repository.analysts.get(db, analyst_id) is None:
        raise AnalystNotFound(f"Аналитик {analyst_id} не найден")
    items, total = repository.documents.page_list(
        db,
        analyst_id,
        title=query.strip().lower() if query and query.strip() else None,
        url=_normalize_url(url).lower() if url and url.strip() else None,
        created_from=created_from,
        created_to=created_to,
        page=page,
        page_size=page_size,
    )
    noted = repository.documents.noted_ids(db, [item.id for item in items])
    return DocumentPage(
        items=[_to_list_item(item, item.id in noted) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


def semantic_documents(
    db,
    analyst_id: int,
    query: str,
    limit: int = 20,
) -> DocumentPage:
    """Семантический поиск: GLM ранжирует заголовки по смыслу запроса."""
    if repository.analysts.get(db, analyst_id) is None:
        raise AnalystNotFound(f"Аналитик {analyst_id} не найден")
    rows = repository.documents.semantic_candidates(db, analyst_id)
    if not rows:
        return DocumentPage(items=[], total=0, page=1, page_size=limit)

    matches = searcher.search(analyst_id, query.strip(), list(rows))
    doc_ids = [doc_id for doc_id, _ in matches]
    docs = {doc.id: doc for doc in repository.documents.fetch_by_ids(db, doc_ids)}
    noted = repository.documents.noted_ids(db, doc_ids)

    items: list[DocumentListItem] = []
    for doc_id, score in matches[:limit]:
        item = _to_list_item(docs[doc_id], doc_id in noted)
        item.score = round(score, 3)
        items.append(item)
    return DocumentPage(items=items, total=len(items), page=1, page_size=limit)


def global_search(db, q: str, limit: int = 8) -> list[SearchHit]:
    """Глобальный поиск по названию — документы всех аналитиков (шапка сервиса)."""
    needle = q.strip().lower()
    if len(needle) < 2:
        return []
    rows = repository.documents.global_search(db, needle, limit)
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


def get_document_card(db, document_id: int) -> DocumentOut:
    """Объект документа для страницы отчёта (с автором и местом в структуре)."""
    doc = get_document(db, document_id)
    analyst = repository.analysts.get(db, doc.analyst_id)
    out = DocumentOut.model_validate(doc)
    # автор — из карточки аналитика; «?» если карточку удалили, а документы остались
    out.analyst_name = analyst.full_name if analyst else "?"
    out.analyst_email = analyst.email if analyst else None
    # структура для крошек: команда и её кластер
    if analyst is not None and analyst.team_id is not None:
        team = repository.org.get_team(db, analyst.team_id)
        if team is not None:
            out.team_id = team.id
            out.team_name = team.name
            out.cluster_id = team.cluster_id
            cluster = repository.org.get_cluster(db, team.cluster_id)
            if cluster is not None:
                out.cluster_name = cluster.name
    return out


def get_note_view(db, document_id: int) -> NoteOut:
    """Заметка руководителя по документу; пустая, если ещё не было."""
    get_document(db, document_id)
    note = repository.documents.get_note(db, document_id)
    if note is None:
        return NoteOut(document_id=document_id, content="")
    return NoteOut.model_validate(note)


def save_note(db, document_id: int, content: str) -> NoteOut:
    """Создать или перезаписать заметку (Markdown, одна на документ)."""
    get_document(db, document_id)
    note = repository.documents.get_note(db, document_id)
    if note is None:
        note = DocumentNote(document_id=document_id, content=content)
        db.add(note)
    else:
        note.content = content
    db.commit()
    db.refresh(note)
    return NoteOut.model_validate(note)


def delete_note(db, document_id: int) -> None:
    """Удалить заметку документа. Идемпотентно: заметки нет — тоже ок."""
    get_document(db, document_id)
    note = repository.documents.get_note(db, document_id)
    if note is not None:
        db.delete(note)
        db.commit()


def missing_document_ids(db, document_ids: list[int]) -> list[int]:
    """Какие из перечисленных id документов не существуют (для 404 batch)."""
    found = repository.documents.existing_ids(db, document_ids)
    return sorted(set(document_ids) - found)


def template_version_exists(db, version_id: int) -> bool:
    """Существует ли версия шаблона (precheck запуска проверки)."""
    return repository.templates.get_version(db, version_id) is not None
