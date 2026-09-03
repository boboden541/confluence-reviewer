"""Реестр аналитиков: карточки, заметки, сводка оценок (ФТ-CR-1, ФТ-CR-2,
ФТ-CR-18)."""

from __future__ import annotations

from app import repository
from app.models import Analyst, AnalystNote
from app.schemas import (
    AnalystCreate,
    AnalystDomainsUpdate,
    AnalystNoteOut,
    AnalystOut,
    AnalystUpdate,
    CriterionSummaryOut,
    RatingsSummaryOut,
)
from app.usecase.exceptions import AnalystEmailTaken, AnalystNotFound
from app.usecase.org import set_analyst_domains
from app.utils import normalize_period_end


def get_analyst(db, analyst_id: int) -> Analyst:
    """Аналитик по id или AnalystNotFound (api переводит в 404)."""
    analyst = repository.analysts.get(db, analyst_id)
    if analyst is None:
        raise AnalystNotFound(f"Аналитик {analyst_id} не найден")
    return analyst


def _to_out(
    db,
    analyst: Analyst,
    documents_count: int,
    contexts: dict[int, tuple[str, int, str, str | None]] | None = None,
) -> AnalystOut:
    """Карточка аналитика с контекстом структуры: команда, кластер, домены.

    contexts — карта команды → (название, id кластера, название кластера,
    цвет) для списков (один join-запрос вместо двух point-lookup'ов на
    аналитика); для одиночной карточки собирается на месте.
    """
    item = AnalystOut.model_validate(analyst)
    item.documents_count = documents_count
    if analyst.team_id is not None:
        if contexts is None:
            contexts = repository.org.team_contexts(db)
        ctx = contexts.get(analyst.team_id)
        if ctx is not None:
            team_name, cluster_id, cluster_name, _color = ctx
            item.team_name = team_name
            item.cluster_id = cluster_id
            item.cluster_name = cluster_name
    return item


def list_analysts(db) -> list[AnalystOut]:
    """ФТ-CR-2: все аналитики с ФИО, email и числом документов."""
    contexts = repository.org.team_contexts(db)
    return [
        _to_out(db, analyst, count, contexts)
        for analyst, count in repository.analysts.list_with_documents_count(db)
    ]


def create_analyst(db, payload: AnalystCreate) -> AnalystOut:
    """ФТ-CR-1: создание карточки аналитика; email уникален."""
    if repository.analysts.get_by_email(db, payload.email) is not None:
        raise AnalystEmailTaken(f"Аналитик с email {payload.email} уже существует")
    analyst = Analyst(
        full_name=payload.full_name.strip(),
        email=payload.email.lower(),
        confluence_username=payload.confluence_username,
    )
    db.add(analyst)
    db.commit()
    db.refresh(analyst)
    return _to_out(db, analyst, 0)


def update_analyst(db, analyst_id: int, payload: AnalystUpdate) -> AnalystOut:
    """Редактирование карточки (ФИО, email, username в Confluence)."""
    analyst = get_analyst(db, analyst_id)
    if repository.analysts.get_by_email(db, payload.email, exclude_id=analyst_id) is not None:
        raise AnalystEmailTaken(f"Аналитик с email {payload.email} уже существует")
    analyst.full_name = payload.full_name.strip()
    analyst.email = payload.email.lower()
    analyst.confluence_username = payload.confluence_username
    db.commit()
    db.refresh(analyst)
    return _to_out(db, analyst, repository.analysts.count_documents(db, analyst.id))


def delete_analyst(db, analyst_id: int) -> None:
    """Удалить аналитика вместе с его документами, отчётами и заметками."""
    analyst = get_analyst(db, analyst_id)
    db.delete(analyst)  # каскад: документы → отчёты и заметки
    db.commit()


def get_analyst_card(db, analyst_id: int) -> AnalystOut:
    """Карточка аналитика с числом документов."""
    analyst = get_analyst(db, analyst_id)
    return _to_out(db, analyst, repository.analysts.count_documents(db, analyst.id))


def update_analyst_domains(db, analyst_id: int, payload: AnalystDomainsUpdate) -> list[str]:
    """Домены аналитика (свободные теги); возвращает применённый список."""
    get_analyst(db, analyst_id)  # 404, если аналитика нет
    return set_analyst_domains(db, analyst_id, payload.domains)


def get_note_view(db, analyst_id: int) -> AnalystNoteOut:
    """Заметка по аналитику в его профиле; пустая, если ещё не было."""
    get_analyst(db, analyst_id)
    note = repository.analysts.get_note(db, analyst_id)
    if note is None:
        return AnalystNoteOut(analyst_id=analyst_id, content="")
    return AnalystNoteOut.model_validate(note)


def save_note(db, analyst_id: int, content: str) -> AnalystNoteOut:
    """Создать или перезаписать заметку (Markdown, одна на аналитика)."""
    get_analyst(db, analyst_id)
    note = repository.analysts.get_note(db, analyst_id)
    if note is None:
        note = AnalystNote(analyst_id=analyst_id, content=content)
        db.add(note)
    else:
        note.content = content
    db.commit()
    db.refresh(note)
    return AnalystNoteOut.model_validate(note)


def delete_note(db, analyst_id: int) -> None:
    """Удалить заметку аналитика. Идемпотентно: заметки нет — тоже ок."""
    get_analyst(db, analyst_id)
    note = repository.analysts.get_note(db, analyst_id)
    if note is not None:
        db.delete(note)
        db.commit()


def ratings_summary(db, analyst_id: int, date_from=None, date_to=None) -> RatingsSummaryOut:
    """Средние оценки руководителя по ИИ-критериям аналитика за период.

    Период отсчитывается по дате создания документа в Confluence
    (created_in_confluence_at): руководитель смотрит, как аналитик работал
    в выбранный период, не таща ретроспективу; дата выставления самой
    оценки не важна. По умолчанию — все документы. Границы включительны
    (date-only «по» охватывает весь последний день); документы без даты
    создания в период не попадают. Снятые оценки («—») записями не являются
    и в статистику не попадают. Сортировка критериев: от сильных к слабым.

    Даты приходят наивными UTC (api привёл aware-границы до guard'а).
    """
    analyst = get_analyst(db, analyst_id)
    date_to_eff = normalize_period_end(date_to) if date_to is not None else None
    rows = repository.ratings.summary_by_analyst(db, analyst.id, date_from, date_to_eff)

    criteria = [
        CriterionSummaryOut(
            criterion_id=row.id,
            code=row.code,
            name=row.name,
            is_archived=row.is_archived,
            average=round(row.average, 2),
            ratings_count=row.ratings_count,
        )
        for row in rows
    ]
    criteria.sort(key=lambda c: (-c.average, c.name.lower()))

    total = sum(c.ratings_count for c in criteria)
    overall = (
        round(sum(c.average * c.ratings_count for c in criteria) / total, 2) if total else None
    )
    return RatingsSummaryOut(
        analyst_id=analyst.id,
        date_from=date_from,
        # эхо — эффективная граница: ответ честно описывает применённый фильтр
        date_to=date_to_eff,
        overall_average=overall,
        total_ratings=total,
        criteria=criteria,
    )
