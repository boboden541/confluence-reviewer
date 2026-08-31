"""API шаблонов требований: список карточек, создание, редактирование,
история версий, пометка «по умолчанию», архив.

Старые роуты /api/template (эпоха одного шаблона) сохранены для обратной
совместимости: работают с шаблоном «по умолчанию»."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models import Template, TemplateVersion
from app.schemas import (
    TemplateCardOut,
    TemplateOut,
    TemplateSave,
    TemplateSection,
    TemplateUpdate,
    TemplateVersionInfo,
)
from app.services.template_store import (
    archive_template,
    create_template,
    find_duplicate_sections,
    find_name_duplicate,
    get_active,
    get_active_version,
    get_default_template,
    list_templates,
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


def _get_template_or_404(template_id: int, db: Session) -> Template:
    template = db.get(Template, template_id)
    if template is None:
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


# --- /api/templates: список карточек, CRUD, пометка, архив ---


@multi_router.get("", response_model=list[TemplateCardOut])
def list_cards(db: Session = Depends(get_db)):
    """Карточки всех шаблонов: активные («по умолчанию» — первым), затем архив."""
    seed_if_missing(db)
    return [_to_card(db, t) for t in list_templates(db)]


@multi_router.post("", response_model=TemplateCardOut, status_code=status.HTTP_201_CREATED)
def create_card(payload: TemplateSave, db: Session = Depends(get_db)):
    """Новый шаблон с нуля: название, описание, маркер и структура разделов.

    Появляется в диалоге проверки сразу с первой версией; «по умолчанию»
    становится, только если это первый шаблон в системе."""
    if find_name_duplicate(db, payload.name) is not None:
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
    )
    return _to_card(db, template)


@multi_router.get("/{template_id}", response_model=TemplateOut)
def get_template_by_id(template_id: int, db: Session = Depends(get_db)):
    """Активная версия шаблона для редактора. id ответа = номер версии."""
    template = _get_template_or_404(template_id, db)
    version = get_active_version(db, template)
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="У шаблона нет активной версии",
        )
    return _to_out(version)


@multi_router.put("/{template_id}", response_model=TemplateOut)
def save_template_version(template_id: int, payload: TemplateSave, db: Session = Depends(get_db)):
    """Сохранить новую версию шаблона (название, описание, маркер, структура).

    Уже созданные отчёты не пересчитываются — шаблон применяется к
    следующим запускам проверки."""
    template = _get_template_or_404(template_id, db)
    if template.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Шаблон в архиве — верните его, чтобы редактировать",
        )
    duplicate = find_name_duplicate(db, payload.name, exclude_id=template.id)
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
def list_template_versions(template_id: int, db: Session = Depends(get_db)):
    """История версий шаблона, свежие сверху."""
    _get_template_or_404(template_id, db)
    rows = db.scalars(
        select(TemplateVersion)
        .where(TemplateVersion.template_id == template_id)
        .order_by(TemplateVersion.id.desc())
    ).all()
    return [
        TemplateVersionInfo(
            id=v.id,
            name=v.name,
            created_at=v.created_at,
            is_active=v.is_active,
            section_count=len(json.loads(v.sections_json)),
        )
        for v in rows
    ]


@multi_router.post("/{template_id}/default", response_model=TemplateCardOut)
def make_default(template_id: int, db: Session = Depends(get_db)):
    """Пометка «по умолчанию»: этот шаблон предвыбран в диалоге проверки."""
    template = _get_template_or_404(template_id, db)
    if template.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Архивный шаблон не может быть «по умолчанию»",
        )
    return _to_card(db, set_default(db, template))


@multi_router.post("/{template_id}/archive", response_model=TemplateCardOut)
def archive(template_id: int, db: Session = Depends(get_db)):
    """Шаблон в архив: не участвует в выборе при проверке; карточка, история
    версий и отчёты остаются. Если он был «по умолчанию» — пометка переходит
    самому свежему из оставшихся."""
    return _to_card(db, archive_template(db, _get_template_or_404(template_id, db)))


@multi_router.post("/{template_id}/restore", response_model=TemplateCardOut)
def restore(template_id: int, db: Session = Depends(get_db)):
    """Вернуть шаблон из архива. Идемпотентно."""
    return _to_card(db, restore_template(db, _get_template_or_404(template_id, db)))


# --- /api/template: legacy-эпоха одного шаблона ---


@router.get("", response_model=TemplateOut)
def get_template(db: Session = Depends(get_db)):
    """Активная версия шаблона «по умолчанию»; при первом обращении (или
    пустой БД) шаблон заливается из requirements_template.json."""
    seed_if_missing(db)
    active = get_active(db)
    if active is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Шаблон требований не настроен: в БД нет версий, "
            "файл первичного шаблона не найден",
        )
    return _to_out(active)


@router.put("", response_model=TemplateOut)
def update_template(payload: TemplateUpdate, db: Session = Depends(get_db)):
    """Сохранить новую версию шаблона «по умолчанию» (legacy-редактор).

    name/description в теле нет — переносятся из предыдущей версии.
    Уже созданные отчёты не пересчитываются."""
    template = get_default_template(db) or next(
        (t for t in list_templates(db) if t.archived_at is None), None
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
def list_versions(db: Session = Depends(get_db)):
    """История версий шаблона «по умолчанию», свежие сверху (legacy)."""
    active = get_active(db)
    if active is None:
        return []
    rows = db.scalars(
        select(TemplateVersion)
        .where(TemplateVersion.template_id == active.template_id)
        .order_by(TemplateVersion.id.desc())
    ).all()
    return [
        TemplateVersionInfo(
            id=v.id,
            name=v.name,
            created_at=v.created_at,
            is_active=v.is_active,
            section_count=len(json.loads(v.sections_json)),
        )
        for v in rows
    ]
