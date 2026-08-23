"""API редактора шаблона требований: просмотр, сохранение, история версий."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import TemplateVersion
from app.schemas import TemplateOut, TemplateSection, TemplateUpdate, TemplateVersionInfo
from app.services.template_store import (
    find_duplicate_sections,
    get_active,
    normalize_sections,
    save_version,
    seed_if_missing,
)

router = APIRouter(prefix="/api/template", tags=["template"])


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


@router.get("", response_model=TemplateOut)
def get_template(db: Session = Depends(get_db)):
    """Активная версия шаблона; при первом обращении (или пустой БД) —
    заливается из файла requirements_template.json."""
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
    """Сохранить новую версию шаблона (маркер названия + структура разделов).

    Уже созданные отчёты не пересчитываются — шаблон применяется к
    следующим запускам проверки.
    """
    sections = normalize_sections([s.model_dump() for s in payload.sections])
    duplicate = find_duplicate_sections(sections)
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Раздел «{duplicate}» повторяется на одном уровне — "
            "переименуйте или удалите один из них",
        )
    version = save_version(db, title_marker=payload.title_marker, sections=sections)
    return _to_out(version)


@router.get("/versions", response_model=list[TemplateVersionInfo])
def list_versions(db: Session = Depends(get_db)):
    """История версий шаблона, свежие сверху."""
    rows = db.scalars(select(TemplateVersion).order_by(TemplateVersion.id.desc())).all()
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
