"""API шаблонов требований: персональные шаблоны (карточки, CRUD, версии,
«по умолчанию», архив) и общий реестр для копирования.

Старые роуты /api/template (эпоха одного шаблона) сохранены для обратной
совместимости: работают с шаблонами текущего пользователя."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_user
from app.models import Template, TemplateVersion, User
from app.schemas import (
    TemplateCardOut,
    TemplateOut,
    TemplateSave,
    TemplateSection,
    TemplateUpdate,
    TemplateVersionInfo,
)
from app.dependencies.auth import resolve_actor
from app.usecase.exceptions import TemplateHasNoActiveVersion, TemplateNotFound
from app.usecase.templates import (
    archive_template,
    copy_template,
    create_template,
    find_duplicate_sections,
    find_name_duplicate,
    get_active,
    get_active_version,
    get_default_template,
    get_template,
    list_templates,
    list_versions,
    normalize_sections,
    restore_template,
    save_version,
    seed_if_missing,
    set_default,
)

router = APIRouter(prefix="/api/template", tags=["template"])
multi_router = APIRouter(prefix="/api/templates", tags=["templates"])


def _to_out(version: TemplateVersion) -> TemplateOut:
    sections = [TemplateSection.model_validate(s) for s in json.loads(version.sections_json)]
    return TemplateOut(
        id=version.id,
        name=version.name,
        description=version.description,
        title_marker=version.title_marker,
        sections=sections,
        created_at=version.created_at,
    )


def _validated_sections(payload_sections: list[TemplateSection]) -> list[dict]:
    """Нормализация + отказ на повторяющихся разделах одного родителя."""
    sections = normalize_sections([s.model_dump() for s in payload_sections])
    duplicate = find_duplicate_sections(sections)
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Раздел «{duplicate}» повторяется на одном уровне — "
            "переименуйте или удалите один из них",
        )
    return sections


def _actor(db: Session, user: User | None) -> User:
    return resolve_actor(db, user)


def _get_own_template_or_404(template_id: int, db: Session, owner_user_id: int) -> Template:
    try:
        template = get_template(db, template_id)
    except TemplateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Шаблон не найден"
        ) from exc
    # чужие шаблоны не существуют для пользователя (в т.ч. редактировать их)
    if template.owner_user_id != owner_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Шаблон не найден")
    return template


def _to_card(db: Session, template: Template) -> TemplateCardOut:
    version = get_active_version(db, template)
    return TemplateCardOut(
        id=template.id,
        name=version.name if version else "—",
        description=version.description if version else None,
        is_default=template.is_default,
        is_archived=template.archived_at is not None,
        active_version_id=version.id if version else None,
        active_version_created_at=version.created_at if version else None,
        section_count=len(json.loads(version.sections_json)) if version else 0,
        title_marker=version.title_marker if version else "",
    )


# --- /api/templates: мои карточки, CRUD, пометка, архив ---


@multi_router.get("", response_model=list[TemplateCardOut])
def list_cards(db: Session = Depends(get_db), user: User | None = Depends(require_user)):
    """Карточки моих шаблонов: активные («по умолчанию» — первым), затем архив."""
    actor = _actor(db, user)
    seed_if_missing(db, owner_user_id=actor.id)
    return [_to_card(db, t) for t in list_templates(db, owner_user_id=actor.id)]


@multi_router.post("", response_model=TemplateCardOut, status_code=status.HTTP_201_CREATED)
def create_card(
    payload: TemplateSave,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    """Новый мой шаблон с нуля: название, описание, маркер и структура разделов.

    Появляется в диалоге проверки сразу с первой версией; «по умолчанию»
    становится, только если это первый мой шаблон."""
    actor = _actor(db, user)
    if find_name_duplicate(db, payload.name, owner_user_id=actor.id) is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Шаблон «{payload.name}» уже есть — назовите по-другому",
        )
    template = create_template(
        db,
        name=payload.name,
        description=payload.description,
        title_marker=payload.title_marker,
        sections=_validated_sections(payload.sections),
        owner_user_id=actor.id,
    )
    return _to_card(db, template)


@multi_router.get("/registry")
def registry(db: Session = Depends(get_db), user: User | None = Depends(require_user)):
    """Общий реестр: неархивные шаблоны всех пользователей, кроме моих."""
    actor = _actor(db, user)
    result = []
    for template in list_templates(db):
        if template.owner_user_id == actor.id or template.archived_at is not None:
            continue
        card = _to_card(db, template)
        result.append(
            {
                "id": template.id,
                "name": card.name,
                "description": card.description,
                "section_count": card.section_count,
                "owner_user_id": template.owner_user_id,
                "is_god_owner": False,
            }
        )
    # авторы — одним запросом
    from app.models import User as UserModel

    from sqlalchemy import select

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


@multi_router.post(
    "/{template_id}/copy", response_model=TemplateCardOut, status_code=status.HTTP_201_CREATED
)
def copy_from_registry(
    template_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    """Добавить себе копию шаблона из общего реестра (копия полностью ваша)."""
    actor = _actor(db, user)
    try:
        template = get_template(db, template_id)
    except TemplateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Шаблон не найден"
        ) from exc
    try:
        copied = copy_template(db, template, owner_user_id=actor.id)
    except TemplateHasNoActiveVersion as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="У шаблона нет активной версии"
        ) from exc
    return _to_card(db, copied)


@multi_router.get("/{template_id}", response_model=TemplateOut)
def get_template_by_id(template_id: int, db: Session = Depends(get_db), user: User | None = Depends(require_user)):
    """Активная версия моего шаблона для редактора. id ответа = номер версии."""
    actor = _actor(db, user)
    template = _get_own_template_or_404(template_id, db, actor.id)
    version = get_active_version(db, template)
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="У шаблона нет активной версии",
        )
    return _to_out(version)


@multi_router.put("/{template_id}", response_model=TemplateOut)
def save_template_version(
    template_id: int,
    payload: TemplateSave,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    """Сохранить новую версию моего шаблона (название, описание, маркер, структура).

    Уже созданные отчёты не пересчитываются — шаблон применяется к
    следующим запускам проверки."""
    actor = _actor(db, user)
    template = _get_own_template_or_404(template_id, db, actor.id)
    if template.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Шаблон в архиве — верните его, чтобы редактировать",
        )
    duplicate = find_name_duplicate(
        db, payload.name, exclude_id=template.id, owner_user_id=actor.id
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Шаблон «{payload.name}» уже есть — назовите по-другому",
        )
    version = save_version(
        db,
        template,
        name=payload.name,
        description=payload.description,
        title_marker=payload.title_marker,
        sections=_validated_sections(payload.sections),
    )
    return _to_out(version)


@multi_router.get("/{template_id}/versions", response_model=list[TemplateVersionInfo])
def list_template_versions(
    template_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    """История версий моего шаблона, свежие сверху."""
    actor = _actor(db, user)
    _get_own_template_or_404(template_id, db, actor.id)
    return [
        TemplateVersionInfo(
            id=v.id,
            name=v.name,
            created_at=v.created_at,
            is_active=v.is_active,
            section_count=len(json.loads(v.sections_json)),
        )
        for v in list_versions(db, template_id)
    ]


@multi_router.post("/{template_id}/default", response_model=TemplateCardOut)
def make_default(
    template_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    """Пометка «по умолчанию»: этот мой шаблон предвыбран в диалоге проверки."""
    actor = _actor(db, user)
    template = _get_own_template_or_404(template_id, db, actor.id)
    if template.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Архивный шаблон не может быть «по умолчанию»",
        )
    return _to_card(db, set_default(db, template))


@multi_router.post("/{template_id}/archive", response_model=TemplateCardOut)
def archive(
    template_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    """Мой шаблон в архив: не участвует в выборе при проверке; карточка, история
    версий и отчёты остаются. Если он был «по умолчанию» — пометка переходит
    самому свежему из оставшихся моих."""
    actor = _actor(db, user)
    return _to_card(db, archive_template(db, _get_own_template_or_404(template_id, db, actor.id)))


@multi_router.post("/{template_id}/restore", response_model=TemplateCardOut)
def restore(
    template_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    """Вернуть мой шаблон из архива. Идемпотентно."""
    actor = _actor(db, user)
    return _to_card(db, restore_template(db, _get_own_template_or_404(template_id, db, actor.id)))


# --- /api/template: legacy-эпоха одного шаблона ---


@router.get("", response_model=TemplateOut)
def get_legacy_template(db: Session = Depends(get_db), user: User | None = Depends(require_user)):
    """Активная версия моего шаблона «по умолчанию»; при первом обращении (или
    пустом наборе) шаблон заливается из requirements_template.json."""
    actor = _actor(db, user)
    seed_if_missing(db, owner_user_id=actor.id)
    active = get_active(db, owner_user_id=actor.id)
    if active is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Шаблон требований не настроен: в БД нет версий, "
            "файл первичного шаблона не найден",
        )
    return _to_out(active)


@router.put("", response_model=TemplateOut)
def update_template(
    payload: TemplateUpdate,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
):
    """Сохранить новую версию моего шаблона «по умолчанию» (legacy-редактор).

    name/description в теле нет — переносятся из предыдущей версии.
    Уже созданные отчёты не пересчитываются."""
    actor = _actor(db, user)
    template = get_default_template(db, owner_user_id=actor.id) or next(
        (t for t in list_templates(db, owner_user_id=actor.id) if t.archived_at is None), None
    )
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Шаблон требований не настроен",
        )
    previous = get_active_version(db, template)
    version = save_version(
        db,
        template,
        name=previous.name if previous else "Шаблон требований",
        description=previous.description if previous else None,
        title_marker=payload.title_marker,
        sections=_validated_sections(payload.sections),
    )
    return _to_out(version)


@router.get("/versions", response_model=list[TemplateVersionInfo])
def list_legacy_versions(
    db: Session = Depends(get_db), user: User | None = Depends(require_user)
):
    """История версий моего шаблона «по умолчанию», свежие сверху (legacy)."""
    actor = _actor(db, user)
    active = get_active(db, owner_user_id=actor.id)
    if active is None:
        return []
    return [
        TemplateVersionInfo(
            id=v.id,
            name=v.name,
            created_at=v.created_at,
            is_active=v.is_active,
            section_count=len(json.loads(v.sections_json)),
        )
        for v in list_versions(db, active.template_id)
    ]
