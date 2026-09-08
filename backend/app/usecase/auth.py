"""Пользователи, роли, заявки и сессии: бизнес-логика авторизации.

Права — фиксированный каталог ключей PERMISSIONS; роль хранит JSON-список
разрешённых. God-роль системная (всё). Токен Confluence — «пароль» лида:
в БД только sha256-хэш.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RegistrationRequest, Role, User
from app.utils import now_utc

# ── каталог прав (ключ → описание для UI «Роли и права») ──────────────

PERMISSIONS: dict[str, str] = {
    "checks": "Запуск проверок и синхронизаций",
    "comments": "Комментарии, заметки, оценки",
    "templates.own": "Свои шаблоны: создание/правка/архив",
    "criteria.own": "Свои критерии ИИ: создание/правка/архив",
    "clusters.edit": "Кластеры: создание/редактирование",
    "teams.edit": "Команды: создание/редактирование/состав",
    "analysts.edit": "Аналитики: создание/редактирование/привязка",
    "lead.assign": "Назначать лида аналитику",
    "delete": "Удаление: кластеры, команды, аналитики",
    "ai.default": "Настройка ИИ «по умолчанию»",
    "moderation": "Модерация заявок и смена ролей",
    "roles.manage": "Создание ролей и настройка их прав",
}

# Стартовый набор роли Lead
LEAD_PERMISSIONS = [
    "checks",
    "comments",
    "templates.own",
    "criteria.own",
    "clusters.edit",
    "teams.edit",
    "analysts.edit",
    "lead.assign",
]

GOD_ROLE_NAME = "God"
LEAD_ROLE_NAME = "Lead"


class PermissionDenied(Exception):
    """У роли пользователя нет нужного права (api → 403)."""


def hash_token(token: str) -> str:
    """sha256 персонального токена: в БД не храним открытый текст."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def permissions_of(role: Role) -> list[str]:
    return json.loads(role.permissions_json)


def role_allows(role: Role, key: str) -> bool:
    if role.is_system:
        return True  # God-роль: все права
    return key in permissions_of(role)


def ensure_permission(user: User | None, key: str) -> None:
    """Проверка права; user=None — авторизация выключена (тесты/локально)."""
    if user is None:
        return
    if not role_allows(user.role, key):
        raise PermissionDenied(
            f"Недостаточно прав: требуется «{PERMISSIONS.get(key, key)}»"
        )


# ── сессии ────────────────────────────────────────────────────────────


def create_session(db: Session, user: User) -> tuple[str, User]:
    token = secrets.token_urlsafe(32)
    from app.models import AuthSession

    db.add(AuthSession(token=token, user_id=user.id))
    user.last_login_at = now_utc()
    db.commit()
    return token, user


def user_for_session(db: Session, token: str) -> User | None:
    from app.models import AuthSession

    session = db.scalar(select(AuthSession).where(AuthSession.token == token))
    if session is None:
        return None
    return db.get(User, session.user_id)


def drop_session(db: Session, token: str) -> None:
    from app.models import AuthSession

    session = db.scalar(select(AuthSession).where(AuthSession.token == token))
    if session is not None:
        db.delete(session)
        db.commit()


# ── пользователи и роли ───────────────────────────────────────────────


def find_user_by_token_hash(db: Session, token_hash: str) -> User | None:
    return db.scalar(select(User).where(User.token_hash == token_hash))


def create_lead_user(
    db: Session, *, login: str, email: str, full_name: str, token_hash: str, role: Role
) -> User:
    user = User(
        confluence_login=login,
        email=email,
        full_name=full_name,
        role_id=role.id,
        token_hash=token_hash,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def list_roles(db: Session) -> list[Role]:
    return list(db.scalars(select(Role).order_by(Role.id)).all())


def get_role(db: Session, role_id: int) -> Role | None:
    return db.get(Role, role_id)


def create_role(db: Session, name: str, permissions: list[str]) -> Role:
    role = Role(name=name.strip(), is_system=False, permissions_json=json.dumps(permissions))
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


def update_role(db: Session, role: Role, *, name: str | None, permissions: list[str] | None) -> Role:
    if name is not None:
        role.name = name.strip()
    if permissions is not None:
        role.permissions_json = json.dumps(permissions)
    db.commit()
    db.refresh(role)
    return role


def delete_role(db: Session, role: Role) -> None:
    db.delete(role)
    db.commit()


def role_in_use(db: Session, role_id: int) -> bool:
    return db.scalar(select(select(User.id).where(User.role_id == role_id).exists())) or False


def list_users(
    db: Session, *, role_name: str | None = None, role_id: int | None = None
) -> list[User]:
    query = select(User).order_by(User.full_name)
    if role_name is not None:
        query = query.join(Role).where(Role.name == role_name)
    if role_id is not None:
        query = query.where(User.role_id == role_id)
    return list(db.scalars(query).all())


def get_user(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


# ── заявки на доступ ──────────────────────────────────────────────────


def find_request_by_token_hash(db: Session, token_hash: str) -> RegistrationRequest | None:
    return db.scalar(select(RegistrationRequest).where(RegistrationRequest.token_hash == token_hash))


def create_request(
    db: Session, *, token_hash: str, login: str, email: str, full_name: str
) -> RegistrationRequest:
    request = RegistrationRequest(
        token_hash=token_hash, confluence_login=login, email=email, full_name=full_name
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


def reapply_request(db: Session, request: RegistrationRequest) -> RegistrationRequest:
    """Повторная подача отклонённой заявки: снова в очередь на модерацию."""
    request.status = "pending"
    request.decided_at = None
    db.commit()
    db.refresh(request)
    return request


def list_requests(db: Session) -> list[RegistrationRequest]:
    return list(
        db.scalars(
            select(RegistrationRequest).order_by(
                RegistrationRequest.status == "pending",
                RegistrationRequest.status != "pending",
                RegistrationRequest.created_at.desc(),
            )
        ).all()
    )


def approve_request(db: Session, request: RegistrationRequest, role: Role) -> User:
    """Одобрить заявку: создать пользователя с выбранной ролью и хэшем
    токена из заявки (этим же токеном он теперь входит)."""
    user = create_lead_user(
        db,
        login=request.confluence_login,
        email=request.email,
        full_name=request.full_name,
        token_hash=request.token_hash,
        role=role,
    )
    request.status = "approved"
    request.role_id = role.id
    request.decided_at = now_utc()
    db.commit()
    return user


def reject_request(db: Session, request: RegistrationRequest) -> RegistrationRequest:
    request.status = "rejected"
    request.decided_at = now_utc()
    db.commit()
    db.refresh(request)
    return request


def approve_user_role(db: Session, user: User, role: Role) -> User:
    user.role_id = role.id
    db.commit()
    db.refresh(user)
    return user


# ── сиды (init_db / lifespan) ─────────────────────────────────────────


def _permissions_json(keys: list[str] | None) -> str:
    return json.dumps(keys if keys is not None else list(PERMISSIONS))


def seed_auth(db: Session, settings: Any) -> None:
    """Роли God/Lead, God-пользователь, владельцы существующего контента.

    Идемпотентно: выполняется при каждом старте, ничего не перетирает.
    """
    god_role = db.scalar(select(Role).where(Role.name == GOD_ROLE_NAME))
    if god_role is None:
        god_role = Role(
            name=GOD_ROLE_NAME, is_system=True, permissions_json=_permissions_json(None)
        )
        db.add(god_role)
        db.flush()
    lead_role = db.scalar(select(Role).where(Role.name == LEAD_ROLE_NAME))
    if lead_role is None:
        db.add(
            Role(
                name=LEAD_ROLE_NAME,
                is_system=False,
                permissions_json=_permissions_json(LEAD_PERMISSIONS),
            )
        )
        db.flush()

    god_user = db.scalar(select(User).where(User.confluence_login == settings.app_username))
    if god_user is None:
        god_user = User(
            confluence_login=settings.app_username,
            email="god@service.local",
            full_name="Администратор сервиса",
            role_id=god_role.id,
            token_hash=None,
        )
        db.add(god_user)
        db.flush()

    # существующий контент (до введения владельцев) достаётся God
    from app.models import AiCriterion, Template

    for template in db.scalars(select(Template).where(Template.owner_user_id.is_(None))).all():
        template.owner_user_id = god_user.id
    for criterion in db.scalars(
        select(AiCriterion).where(AiCriterion.owner_user_id.is_(None))
    ).all():
        criterion.owner_user_id = god_user.id
    db.commit()


def default_owner_id(db: Session) -> int | None:
    """Владелец по умолчанию для автосидов контента (God), если он создан."""
    from sqlalchemy import select

    from app.models import Role as RoleModel

    god_role = db.scalar(select(RoleModel).where(RoleModel.name == GOD_ROLE_NAME))
    if god_role is None:
        return None
    return db.scalar(select(User.id).where(User.role_id == god_role.id).limit(1))
