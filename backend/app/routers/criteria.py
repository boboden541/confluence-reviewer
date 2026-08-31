"""API справочника ИИ-критериев (раздел настроек): список, создание,
редактирование, архив и восстановление. Критерии — источник сборки промта
прогона и объект оценок руководителя, поэтому физического удаления нет."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models import AiCriterion
from app.schemas import AiCriterionCreate, AiCriterionOut, AiCriterionUpdate
from app.usecase.criteria import (
    _unique_code,
    get_criterion,
    list_criteria as list_all_criteria,
    seed_criteria_if_missing,
    slugify_code,
)
from app.usecase.exceptions import CriterionNotFound

router = APIRouter(prefix="/api/ai-criteria", tags=["ai-criteria"])


def _get_criterion_or_404(criterion_id: int, db: Session) -> AiCriterion:
    try:
        return get_criterion(db, criterion_id)
    except CriterionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Критерий не найден"
        ) from exc


@router.get("", response_model=list[AiCriterionOut])
def list_criteria(db: Session = Depends(get_db)):
    """Все критерии: активные, затем архивные (справочник в настройках)."""
    seed_criteria_if_missing(db)
    return list_all_criteria(db)


@router.post("", response_model=AiCriterionOut, status_code=status.HTTP_201_CREATED)
def create_criterion(payload: AiCriterionCreate, db: Session = Depends(get_db)):
    """Новый критерий. Код генерируется из названия и дальше не меняется."""
    criterion = AiCriterion(
        code=_unique_code(db, slugify_code(payload.name)),
        name=payload.name,
        prompt=payload.prompt,
    )
    db.add(criterion)
    db.commit()
    db.refresh(criterion)
    return criterion


@router.put("/{criterion_id}", response_model=AiCriterionOut)
def update_criterion(
    criterion_id: int, payload: AiCriterionUpdate, db: Session = Depends(get_db)
):
    """Переименовать и/или изменить промт. Изменение промта меняет собранный
    промт следующих прогонов; про переименование UI предупреждает — его увидят
    и прошлые оценки в статистике."""
    criterion = _get_criterion_or_404(criterion_id, db)
    criterion.name = payload.name
    criterion.prompt = payload.prompt
    db.commit()
    db.refresh(criterion)
    return criterion


@router.delete("/{criterion_id}", response_model=AiCriterionOut)
def archive_criterion(criterion_id: int, db: Session = Depends(get_db)):
    """Удаление = архив: критерий выпадает из новых проверок, но остаётся в
    статистике и может быть восстановлен. Идемпотентно."""
    criterion = _get_criterion_or_404(criterion_id, db)
    criterion.is_archived = True
    db.commit()
    db.refresh(criterion)
    return criterion


@router.post("/{criterion_id}/restore", response_model=AiCriterionOut)
def restore_criterion(criterion_id: int, db: Session = Depends(get_db)):
    """Вернуть критерий из архива в активные."""
    criterion = _get_criterion_or_404(criterion_id, db)
    criterion.is_archived = False
    db.commit()
    db.refresh(criterion)
    return criterion
