import re
import secrets
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import rate_limit
from app.core.config import get_settings
from app.core.errors import Conflict, NotFound, Unauthorized, ValidationFailed
from app.core.permissions import permissions_for
from app.core.security import (
    csrf_token_for_session,
    hash_password,
    hash_token,
    new_token,
    password_needs_rehash,
    verify_password,
)
from app.models import (
    PasswordResetToken,
    Role,
    User,
    UserSession,
    Workspace,
    WorkspaceMember,
)
from app.models.base import utcnow
from app.schemas.auth import MeResponse, RegisterRequest, UserOut, WorkspaceRef
from app.services import audit


@dataclass
class IssuedSession:
    token: str
    csrf_token: str
    session: UserSession


def normalize_email(email: str) -> str:
    return email.strip().lower()


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:40] or "workspace"
    return f"{base}-{secrets.token_hex(3)}"


def issue_session(
    db: Session, user: User, workspace_id: uuid.UUID | None, user_agent: str | None
) -> IssuedSession:
    token = new_token()
    token_hash = hash_token(token)
    session = UserSession(
        user_id=user.id,
        token_hash=token_hash,
        active_workspace_id=workspace_id,
        expires_at=utcnow() + timedelta(hours=get_settings().session_ttl_hours),
        user_agent=(user_agent or "")[:255] or None,
    )
    db.add(session)
    return IssuedSession(
        token=token, csrf_token=csrf_token_for_session(token_hash), session=session
    )


def register(
    db: Session, data: RegisterRequest, *, ip: str | None, user_agent: str | None
) -> tuple[User, IssuedSession]:
    settings = get_settings()
    rate_limit.hit(
        "register", ip or "unknown", limit=settings.register_limit_per_hour, window_seconds=3600
    )
    email = normalize_email(data.email)
    if db.scalar(select(User.id).where(User.email == email)):
        raise Conflict(
            "Não foi possível concluir o cadastro com este e-mail.", code="email_unavailable"
        )
    if data.password.lower() == email:
        raise ValidationFailed("A senha não pode ser igual ao e-mail.")

    user = User(email=email, full_name=data.full_name, password_hash=hash_password(data.password))
    workspace = Workspace(name=data.workspace_name, slug=slugify(data.workspace_name))
    db.add_all([user, workspace])
    db.flush()
    workspace.created_by_id = user.id
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=Role.ADMIN))
    issued = issue_session(db, user, workspace.id, user_agent)
    user.last_login_at = utcnow()
    audit.record(
        db,
        "auth.register",
        workspace_id=workspace.id,
        actor_id=user.id,
        entity_type="user",
        entity_id=user.id,
        ip=ip,
    )
    audit.record(
        db,
        "workspace.created",
        workspace_id=workspace.id,
        actor_id=user.id,
        entity_type="workspace",
        entity_id=workspace.id,
        ip=ip,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict(
            "Não foi possível concluir o cadastro com este e-mail.", code="email_unavailable"
        ) from exc
    return user, issued


def login(
    db: Session, email: str, password: str, *, ip: str | None, user_agent: str | None
) -> tuple[User, IssuedSession]:
    settings = get_settings()
    email = normalize_email(email)
    rate_limit.hit(
        "login-ip", ip or "unknown", limit=settings.login_limit_per_5min * 5, window_seconds=300
    )
    rate_limit.hit(
        "login", f"{email}|{ip}", limit=settings.login_limit_per_5min, window_seconds=300
    )

    user = db.scalar(select(User).where(User.email == email))
    if (
        not verify_password(user.password_hash if user else None, password)
        or user is None
        or not user.is_active
    ):
        audit.record(
            db,
            "auth.login_failed",
            actor_id=user.id if user else None,
            details={"reason": "credenciais_invalidas"},
            ip=ip,
        )
        db.commit()
        raise Unauthorized("E-mail ou senha inválidos.", code="invalid_credentials")

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    membership = db.scalar(
        select(WorkspaceMember)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(WorkspaceMember.created_at)
        .limit(1)
    )
    issued = issue_session(db, user, membership.workspace_id if membership else None, user_agent)
    user.last_login_at = utcnow()
    audit.record(
        db,
        "auth.login",
        workspace_id=membership.workspace_id if membership else None,
        actor_id=user.id,
        entity_type="user",
        entity_id=user.id,
        ip=ip,
    )
    db.commit()
    rate_limit.reset("login", f"{email}|{ip}")
    return user, issued


def logout(db: Session, session: UserSession, *, ip: str | None) -> None:
    session.revoked_at = utcnow()
    audit.record(
        db, "auth.logout", workspace_id=session.active_workspace_id, actor_id=session.user_id, ip=ip
    )
    db.commit()


def build_me(db: Session, user: User, session: UserSession) -> MeResponse:
    workspace_ref = None
    permissions: list[str] = []
    if session.active_workspace_id is not None:
        row = db.execute(
            select(Workspace, WorkspaceMember.role)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(Workspace.id == session.active_workspace_id, WorkspaceMember.user_id == user.id)
        ).first()
        if row is not None:
            workspace, role = row
            workspace_ref = WorkspaceRef(
                id=workspace.id, name=workspace.name, slug=workspace.slug, role=role
            )
            permissions = sorted(p.value for p in permissions_for(role))
    return MeResponse(
        user=UserOut.model_validate(user),
        workspace=workspace_ref,
        permissions=permissions,
        csrf_token=csrf_token_for_session(session.token_hash),
    )


def request_password_reset(db: Session, email: str, *, ip: str | None) -> str | None:
    """Cria o token e retorna-o (para envio por e-mail) ou None. A resposta HTTP é sempre igual."""
    settings = get_settings()
    email = normalize_email(email)
    rate_limit.hit(
        "forgot-ip", ip or "unknown", limit=settings.forgot_limit_per_hour * 4, window_seconds=3600
    )
    rate_limit.hit("forgot", email, limit=settings.forgot_limit_per_hour, window_seconds=3600)
    user = db.scalar(select(User).where(User.email == email, User.is_active.is_(True)))
    if user is None:
        return None
    now = utcnow()
    db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    token = new_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=now + timedelta(minutes=settings.password_reset_ttl_minutes),
        )
    )
    audit.record(
        db,
        "auth.password_reset_requested",
        actor_id=user.id,
        entity_type="user",
        entity_id=user.id,
        ip=ip,
    )
    db.commit()
    return token


def reset_password(db: Session, token: str, password: str, *, ip: str | None) -> None:
    now = utcnow()
    record = db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == hash_token(token),
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
    )
    if record is None:
        raise ValidationFailed(
            "Link de redefinição inválido ou expirado.", code="invalid_reset_token"
        )
    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise ValidationFailed(
            "Link de redefinição inválido ou expirado.", code="invalid_reset_token"
        )
    if password.lower() == user.email:
        raise ValidationFailed("A senha não pode ser igual ao e-mail.")
    user.password_hash = hash_password(password)
    record.used_at = now
    # Toda sessão existente é encerrada após a troca de senha.
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    audit.record(
        db, "auth.password_reset", actor_id=user.id, entity_type="user", entity_id=user.id, ip=ip
    )
    db.commit()


def switch_workspace(
    db: Session, session: UserSession, workspace_id: uuid.UUID, *, ip: str | None
) -> None:
    membership = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == session.user_id
        )
    )
    if membership is None:
        # Mesmo erro para workspace inexistente ou alheio: não revela existência.
        raise NotFound("Workspace não encontrado.")
    session.active_workspace_id = workspace_id
    audit.record(
        db, "workspace.switched", workspace_id=workspace_id, actor_id=session.user_id, ip=ip
    )
    db.commit()
