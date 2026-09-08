"""API персонального справочника ИИ-критериев: список, создание,
редактирование, архив и восстановление СВОИХ критериев; общий реестр —
просмотр всех и копирование себе. Критерии — источник сборки промта
прогона и объект оценок, физического удаления нет."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_user
from app.dependencies.auth import resolve_actor
from app.models import AiCriterion, User
from app.schemas import AiCriterionCreate, AiCriterionOut, AiCriterionUpdate
from app.usecase.criteria import (
    _unique_code,
    copy_criterion,
    get_criterion,
    list_criteria,
    seed_criteria_if_missing,
    slugify_code,
)
from app.usecase.exceptions import CriterionNotFound

router = APIRouter(prefix="/api/ai-criteria", tags=["ai-criteria"])


def _actor(db: Session, user: User | None) -> User:
    return resolve_actor(db, user)


def _get_own_criterion_or_404(criterion_id: int, db: Session, owner_user_id: int) -> AiCriterion:
    try:
        criterion = get_criterion(db, criterion_id)
    except CriterionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Критерий не найден"
        ) from exc
    if criterion.owner_user_id != owner_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Критерий не найден")
    return criterion


@router.get("", response_model=list[AiCriterionOut])
def list_criteria_view(db: Session = Depends(get_db), user: User | None = Depends(require_user)):
    """Мои критерии: активные, затем архивные."""
    actor = _actor(db, user)
    seed_criteria_if_missing(db, owner_user_id=actor.id)
    return list_criteria(db, owner_user_id=actor.id)


@router.get("/registry")
def registry(db: Session = Depends(get_db), user: User | None = Depends(require_user)):
    """Общий реестр: критерии всех пользователей, кроме моих."""
    actor = _actor(db, user)
    result = []
    for criterion in list_criteria(db):
        if criterion.owner_user_id == actor.id:
            continue
        result.append(
            {
                "id": criterion.id,
                "name": criterion.name,
                "prompt": criterion.prompt,
                "is_archived": criterion.is_archived,
                "owner_user_id": criterion.owner_user_id,
            }
        )
    from sqlalchemy import select

    from app.models import User as UserModel

    owners = {
        u.id: u.full_name
        for u in db.scalars(
            select(UserModel).where(
                UserModel.id.in_([r["owner_user_id"] for r in result] or [0])
            )
        ).all()
    }
    for item in result:
        item["owner_name"] = owners.get(item["owner_user_id"], "?")
    return result


@router.post(
    "/{criterion_id}/copy", response_model=AiCriterionOut, status_code=status.HTTP_201_CREATED
)
def copy_from_registry(
    criterion_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    """Добавить себе копию критерия из общего реестра."""
    actor = _actor(db, user)
    try:
        criterion = get_criterion(db, criterion_id)
    except CriterionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Критерий не найден"
        ) from exc
    return copy_criterion(db, criterion, owner_user_id=actor.id)


@router.post("", response_model=AiCriterionOut, status_code=status.HTTP_201_CREATED)
def create_criterion(
    payload: AiCriterionCreate,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    """Новый мой критерий. Код генерируется из названия и дальше не меняется."""
    actor = _actor(db, user)
    criterion = AiCriterion(
        code=_unique_code(db, slugify_code(payload.name)),
        name=payload.name,
        prompt=payload.prompt,
        owner_user_id=actor.id,
    )
    db.add(criterion)
    db.commit()
    db.refresh(criterion)
    return criterion


@router.put("/{criterion_id}", response_model=AiCriterionOut)
def update_criterion(
    criterion_id: int,
    payload: AiCriterionUpdate,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    """Переименовать и/или изменить промт моего критерия."""
    criterion = _get_own_criterion_or_404(criterion_id, db, _actor(db, user).id)
    criterion.name = payload.name
    criterion.prompt = payload.prompt
    db.commit()
    db.refresh(criterion)
    return criterion


@router.delete("/{criterion_id}", response_model=AiCriterionOut)
def archive_criterion(
    criterion_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    """Удаление = архив моего критерия. Идемпотентно."""
    criterion = _get_own_criterion_or_404(criterion_id, db, _actor(db, user).id)
    criterion.is_archived = True
    db.commit()
    db.refresh(criterion)
    return criterion


@router.post("/{criterion_id}/restore", response_model=AiCriterionOut)
def restore_criterion(
    criterion_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    """Вернуть мой критерий из архива в активные."""
    criterion = _get_own_criterion_or_404(criterion_id, db, _actor(db, user).id)
    criterion.is_archived = False
    db.commit()
    db.refresh(criterion)
    return criterion
