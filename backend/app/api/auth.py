"""Вход (God — логин+пароль, лиды — токен Confluence), заявки, роли, сессии."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.dependencies import get_db
from app.dependencies.auth import require_permission, require_user
from app.models import Analyst, RegistrationRequest, Role, User
from app.schemas.auth import (
    ApproveInput,
    LoginInput,
    MeOut,
    RegistrationRequestOut,
    ReapplyInput,
    RoleInput,
    RoleOut,
    SessionOut,
    TokenLoginInput,
    UserBrief,
)
from app.usecase import auth as auth_uc
from app.usecase.ai_settings import ai_configured

router = APIRouter(prefix="/api/auth", tags=["auth"])
roles_router = APIRouter(prefix="/api/roles", tags=["roles"])
users_router = APIRouter(prefix="/api/users", tags=["users"])


def _role_out(role: Role) -> RoleOut:
    return RoleOut(
        id=role.id,
        name=role.name,
        is_system=role.is_system,
        permissions=auth_uc.permissions_of(role),
    )


def _me(db: Session, user: User) -> MeOut:
    return MeOut(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        role_id=user.role_id,
        role_name=user.role.name,
        is_god=user.role.is_system,
        permissions=auth_uc.permissions_of(user.role),
        ai_configured=ai_configured(db, user),
        pending_requests=db.scalar(
            select(func.count())
            .select_from(RegistrationRequest)
            .where(RegistrationRequest.status == "pending")
        )
        or 0,
    )


@router.post("/login", response_model=SessionOut)
def login(payload: LoginInput, request: Request, db: Session = Depends(get_db)):
    """Вход God: логин и пароль, заданные в окружении сервиса."""
    state = request.app.state.auth
    # пустой пароль в конфигурации = вход запрещён целиком (misconfiguration)
    if not state.get("password"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль"
        )
    if not (
        secrets.compare_digest(
            payload.username.encode("utf-8"), str(state.get("username", "")).encode("utf-8")
        )
        and secrets.compare_digest(
            payload.password.encode("utf-8"), str(state.get("password", "")).encode("utf-8")
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль"
        )
    user = db.scalar(select(User).where(User.confluence_login == state.get("username")))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Учётная запись администратора не инициализирована",
        )
    token, user = auth_uc.create_session(db, user)
    return SessionOut(token=token, user=_me(db, user))


async def _token_login(payload: TokenLoginInput, db: Session):
    """Общая механика входа по токену: сессия / статусы заявки / создание."""
    token_hash = auth_uc.hash_token(payload.token)
    user = auth_uc.find_user_by_token_hash(db, token_hash)
    if user is not None:
        token, user = auth_uc.create_session(db, user)
        return SessionOut(token=token, user=_me(db, user))

    request = auth_uc.find_request_by_token_hash(db, token_hash)
    if request is not None and request.status == "pending":
        return _request_status(request)
    if request is not None and request.status == "rejected":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Заявка отклонена — вы можете подать её повторно",
        )

    # незнакомый токен: проверяем в Confluence и заводим заявку
    from app.clients.confluence import ConfluenceClient, ConfluenceError

    settings = get_settings()
    try:
        async with ConfluenceClient(settings, bearer_token=payload.token) as client:
            who = await client.whoami()
    except ConfluenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Confluence недоступен или токен неверен: {exc}",
        ) from exc

    login = str(who.get("username") or who.get("account_id") or "").strip()
    if not login:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Confluence не вернул логин для этого токена",
        )
    request = auth_uc.create_request(
        db,
        token_hash=token_hash,
        login=login,
        email=str(who.get("email") or "").strip(),
        full_name=str(who.get("fullName") or login).strip(),
    )
    return _request_status(request)


def _request_status(request: RegistrationRequest):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "status": "pending",
            "detail": "Заявка на доступ отправлена администратору",
            "full_name": request.full_name,
            "email": request.email,
            "confluence_login": request.confluence_login,
        },
    )


@router.post("/token-login", response_model=None)
async def token_login(payload: TokenLoginInput, db: Session = Depends(get_db)):
    """Вход лидов персональным токеном Confluence."""
    return await _token_login(payload, db)


@router.post("/reapply")
async def reapply(payload: ReapplyInput, db: Session = Depends(get_db)):
    """Повторная подача отклонённой заявки тем же токеном."""
    token_hash = auth_uc.hash_token(payload.token)
    request = auth_uc.find_request_by_token_hash(db, token_hash)
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Заявка не найдена — подайте новую"
        )
    if request.status == "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Заявка уже одобрена — просто войдите"
        )
    request = auth_uc.reapply_request(db, request)
    return _request_status(request)


@router.get("/me", response_model=MeOut)
def me(db: Session = Depends(get_db), user: User | None = Depends(require_user)):
    from app.dependencies.auth import resolve_actor

    return _me(db, resolve_actor(db, user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, db: Session = Depends(get_db)):
    """Выйти: удалить сессию из заголовка (если авторизация включена)."""
    if request.app.state.auth.get("enabled"):
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            auth_uc.drop_session(db, auth.removeprefix("Bearer ").strip())
    return None


# ── заявки и роли (god) ──────────────────────────────────────────────


@router.get("/requests", response_model=list[RegistrationRequestOut])
def list_requests(
    db: Session = Depends(get_db),
    _: User | None = Depends(require_permission("moderation")),
):
    return auth_uc.list_requests(db)


@router.post("/requests/{request_id}/approve", response_model=RegistrationRequestOut)
def approve_request(
    request_id: int,
    payload: ApproveInput,
    db: Session = Depends(get_db),
    _: User | None = Depends(require_permission("moderation")),
):
    request = db.get(RegistrationRequest, request_id)
    if request is None or request.status == "approved":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявка не найдена")
    role = auth_uc.get_role(db, payload.role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Роль не найдена")
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Системную роль нельзя назначать"
        )
    auth_uc.approve_request(db, request, role)
    db.refresh(request)
    return request


@router.post("/requests/{request_id}/reject", response_model=RegistrationRequestOut)
def reject_request(
    request_id: int,
    db: Session = Depends(get_db),
    _: User | None = Depends(require_permission("moderation")),
):
    request = db.get(RegistrationRequest, request_id)
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявка не найдена")
    return auth_uc.reject_request(db, request)


@router.post("/requests/{request_id}/reopen", response_model=RegistrationRequestOut)
def reopen_request(
    request_id: int,
    db: Session = Depends(get_db),
    _: User | None = Depends(require_permission("moderation")),
):
    """Вернуть отклонённую заявку в новые (по просьбе подавшего повторно)."""
    request = db.get(RegistrationRequest, request_id)
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявка не найдена")
    return auth_uc.reapply_request(db, request)


@router.put("/users/{user_id}/role", response_model=MeOut)
def change_user_role(
    user_id: int,
    payload: ApproveInput,
    db: Session = Depends(get_db),
    _: User | None = Depends(require_permission("moderation")),
):
    user = auth_uc.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    role = auth_uc.get_role(db, payload.role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Роль не найдена")
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Системную роль нельзя назначать"
        )
    user = auth_uc.approve_user_role(db, user, role)
    return _me(db, user)


# ── роли (просмотр — всем, правка — god) ─────────────────────────────


@roles_router.get("", response_model=list[RoleOut])
def list_roles(db: Session = Depends(get_db), _: User | None = Depends(require_user)):
    return [_role_out(r) for r in auth_uc.list_roles(db)]


@roles_router.get("/permissions")
def permissions_catalog(_: User | None = Depends(require_user)):
    return auth_uc.PERMISSIONS


@roles_router.post("", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def create_role(
    payload: RoleInput,
    db: Session = Depends(get_db),
    _: User | None = Depends(require_permission("roles.manage")),
):
    unknown = [key for key in payload.permissions if key not in auth_uc.PERMISSIONS]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Неизвестные права: {', '.join(unknown)}",
        )
    if any(r.name == payload.name.strip() for r in auth_uc.list_roles(db)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Роль «{payload.name}» уже существует"
        )
    return _role_out(auth_uc.create_role(db, payload.name, payload.permissions))


@roles_router.put("/{role_id}", response_model=RoleOut)
def update_role(
    role_id: int,
    payload: RoleInput,
    db: Session = Depends(get_db),
    _: User | None = Depends(require_permission("roles.manage")),
):
    role = auth_uc.get_role(db, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Роль не найдена")
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Системную роль нельзя изменять"
        )
    unknown = [key for key in payload.permissions if key not in auth_uc.PERMISSIONS]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Неизвестные права: {', '.join(unknown)}",
        )
    return _role_out(auth_uc.update_role(db, role, name=payload.name, permissions=payload.permissions))


@roles_router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    _: User | None = Depends(require_permission("roles.manage")),
):
    role = auth_uc.get_role(db, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Роль не найдена")
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Системную роль нельзя удалять"
        )
    if auth_uc.role_in_use(db, role_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Роль назначена пользователям — сначала смените им роль",
        )
    auth_uc.delete_role(db, role)


# ── пользователи (для назначения лида) ───────────────────────────────


@users_router.get("", response_model=list[UserBrief])
def list_users(
    role: str | None = Query(default=None, max_length=64),
    role_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User | None = Depends(require_permission("lead.assign")),
):
    users = auth_uc.list_users(db, role_name=role, role_id=role_id)
    counts = dict(
        db.execute(
            select(Analyst.lead_user_id, func.count()).group_by(Analyst.lead_user_id)
        ).all()
    )
    return [
        UserBrief(
            id=u.id,
            full_name=u.full_name,
            email=u.email,
            role_name=u.role.name,
            analysts_count=counts.get(u.id, 0),
        )
        for u in users
    ]
