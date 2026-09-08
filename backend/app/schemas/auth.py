"""Схемы авторизации: вход, пользователь, роли, заявки."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(max_length=255)


class TokenLoginInput(BaseModel):
    token: str = Field(min_length=8, max_length=512)


class ReapplyInput(TokenLoginInput):
    pass


class RoleOut(BaseModel):
    id: int
    name: str
    is_system: bool
    permissions: list[str]

    class Config:
        from_attributes = True


class RoleInput(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    permissions: list[str] = Field(default_factory=list)


class UserBrief(BaseModel):
    id: int
    full_name: str
    email: str
    role_name: str
    analysts_count: int = 0


class MeOut(BaseModel):
    id: int
    full_name: str
    email: str
    role_id: int
    role_name: str
    is_god: bool
    permissions: list[str]
    ai_configured: bool
    pending_requests: int = 0


class SessionOut(BaseModel):
    token: str
    user: MeOut


class RegistrationRequestOut(BaseModel):
    id: int
    confluence_login: str
    email: str
    full_name: str
    status: str
    role_id: int | None = None
    created_at: datetime
    decided_at: datetime | None = None

    class Config:
        from_attributes = True


class ApproveInput(BaseModel):
    role_id: int
