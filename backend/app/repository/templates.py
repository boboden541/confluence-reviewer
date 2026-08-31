"""Выборки шаблонов требований и их версий."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Template, TemplateVersion


def get(db: Session, template_id: int) -> Template | None:
    return db.get(Template, template_id)


def get_version(db: Session, version_id: int) -> TemplateVersion | None:
    return db.get(TemplateVersion, version_id)


def get_active_version(db: Session, template: Template) -> TemplateVersion | None:
    """Активная версия шаблона (внутри контейнера ровно одна)."""
    return db.scalar(
        select(TemplateVersion)
        .where(TemplateVersion.template_id == template.id, TemplateVersion.is_active)
        .order_by(TemplateVersion.id.desc())
    )


def list_containers(db: Session) -> list[Template]:
    """Все контейнеры шаблонов в порядке id."""
    return list(db.scalars(select(Template).order_by(Template.id)).all())


def list_not_archived(db: Session) -> list[Template]:
    return list(
        db.scalars(select(Template).where(Template.archived_at.is_(None))).all()
    )


def list_others(db: Session, template_id: int) -> list[Template]:
    """Все шаблоны, кроме заданного (переключение пометки «по умолчанию»)."""
    return list(
        db.scalars(select(Template).where(Template.id != template_id)).all()
    )


def get_default(db: Session) -> Template | None:
    return db.scalar(select(Template).where(Template.is_default, Template.archived_at.is_(None)))


def any_exists(db: Session) -> bool:
    return db.scalar(select(Template.id).limit(1)) is not None


def list_versions_desc(db: Session, template_id: int) -> list[TemplateVersion]:
    """История версий шаблона, свежие сверху."""
    return list(
        db.scalars(
            select(TemplateVersion)
            .where(TemplateVersion.template_id == template_id)
            .order_by(TemplateVersion.id.desc())
        ).all()
    )
