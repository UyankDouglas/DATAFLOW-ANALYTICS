"""Dependências de requisição: sessão, workspace ativo validado no servidor e RBAC."""

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_session_factory
from app.core.errors import Forbidden, Unauthorized
from app.core.permissions import Permission, permissions_for
from app.core.security import hash_token
from app.models import User, UserSession, WorkspaceMember
from app.models.base import utcnow


def get_db() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def client_ip(request: Request) -> str | None:
    # O Uvicorn roda com --proxy-headers atrás do proxy reverso confiável.
    return request.client.host if request.client else None


@dataclass
class AuthSession:
    session: UserSession
    user: User


@dataclass
class RequestContext:
    user: User
    session: UserSession
    workspace_id: uuid.UUID
    role: str
    permissions: frozenset[Permission]
    ip: str | None

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions


def get_auth_session(request: Request, db: Session = Depends(get_db)) -> AuthSession:
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        raise Unauthorized()
    now = utcnow()
    row = db.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(
            UserSession.token_hash == hash_token(token),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
            User.is_active.is_(True),
        )
    ).first()
    if row is None:
        raise Unauthorized()
    user_session, user = row
    if now - user_session.last_seen_at > timedelta(minutes=5):
        user_session.last_seen_at = now
        db.commit()
    return AuthSession(session=user_session, user=user)


def get_context(
    request: Request, auth: AuthSession = Depends(get_auth_session), db: Session = Depends(get_db)
) -> RequestContext:
    workspace_id = auth.session.active_workspace_id
    if workspace_id is None:
        raise Forbidden("Nenhum workspace ativo para esta sessão.", code="no_workspace")
    # O pertencimento é revalidado a cada requisição; o papel vem sempre do banco.
    membership = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == auth.user.id,
        )
    )
    if membership is None:
        raise Forbidden("Você não pertence mais a este workspace.", code="not_a_member")
    return RequestContext(
        user=auth.user,
        session=auth.session,
        workspace_id=workspace_id,
        role=membership.role,
        permissions=permissions_for(membership.role),
        ip=client_ip(request),
    )


def require(permission: Permission) -> Callable[..., RequestContext]:
    def dependency(ctx: RequestContext = Depends(get_context)) -> RequestContext:
        if not ctx.can(permission):
            raise Forbidden()
        return ctx

    return dependency
