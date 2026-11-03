"""Membros, convites e configurações do workspace.

Regras que o servidor garante:
- o workspace nunca fica sem administrador (não é possível rebaixar nem remover o último);
- convites guardam só o hash do token; a resposta é a mesma exista ou não conta com o e-mail;
- aceitar exige estar logado com o e-mail convidado; o papel vem do convite, nunca do cliente;
- quem é removido perde o acesso na próxima requisição (o pertencimento é relido sempre).
"""

import uuid
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import RequestContext
from app.core.config import get_settings
from app.core.errors import Conflict, Forbidden, Gone, NotFound, ValidationFailed
from app.core.security import hash_token, new_token
from app.models import Role, User, UserSession, Workspace, WorkspaceInvitation, WorkspaceMember
from app.models.base import utcnow
from app.schemas.workspace import (
    InvitationOut,
    InvitationPreview,
    WorkspaceSettings,
    WorkspaceSettingsOut,
    WorkspaceUpdate,
)
from app.services import audit
from app.services.auth_service import normalize_email
from app.tasks.dispatch import enqueue_invitation_email


def _admins(db: Session, workspace_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == Role.ADMIN)
        )
        or 0
    )


def _member(db: Session, workspace_id: uuid.UUID, member_id: uuid.UUID) -> WorkspaceMember:
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.id == member_id, WorkspaceMember.workspace_id == workspace_id
        )
    )
    if member is None:
        raise NotFound("Membro não encontrado.")
    return member


def _keep_an_admin(db: Session, member: WorkspaceMember) -> None:
    if member.role == Role.ADMIN and _admins(db, member.workspace_id) <= 1:
        raise Conflict(
            "O workspace precisa de ao menos um administrador. Promova outra pessoa antes.",
            code="last_admin",
        )


def change_role(db: Session, ctx: RequestContext, member_id: uuid.UUID, role: str) -> None:
    member = _member(db, ctx.workspace_id, member_id)
    if member.role == role:
        return
    if role != Role.ADMIN:
        _keep_an_admin(db, member)
    previous, member.role = member.role, role
    audit.record(
        db,
        "member.role_changed",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="member",
        entity_id=member.id,
        details={"user_id": str(member.user_id), "from": previous, "to": role},
        ip=ctx.ip,
    )
    db.commit()


def remove_member(db: Session, ctx: RequestContext, member_id: uuid.UUID) -> None:
    member = _member(db, ctx.workspace_id, member_id)
    _keep_an_admin(db, member)
    # Sessões abertas nesse workspace deixam de tê-lo como ativo.
    db.execute(
        update(UserSession)
        .where(
            UserSession.user_id == member.user_id,
            UserSession.active_workspace_id == ctx.workspace_id,
        )
        .values(active_workspace_id=None)
    )
    audit.record(
        db,
        "member.removed",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="member",
        entity_id=member.id,
        details={"user_id": str(member.user_id), "role": member.role},
        ip=ctx.ip,
    )
    db.delete(member)
    db.commit()


# ---------------------------------------------------------------- convites


def _pending(db: Session, workspace_id: uuid.UUID) -> list[WorkspaceInvitation]:
    return list(
        db.scalars(
            select(WorkspaceInvitation)
            .where(
                WorkspaceInvitation.workspace_id == workspace_id,
                WorkspaceInvitation.accepted_at.is_(None),
                WorkspaceInvitation.revoked_at.is_(None),
                WorkspaceInvitation.expires_at > utcnow(),
            )
            .order_by(WorkspaceInvitation.created_at.desc())
        ).all()
    )


def list_invitations(db: Session, workspace_id: uuid.UUID) -> list[InvitationOut]:
    invitations = _pending(db, workspace_id)
    ids = {i.invited_by_id for i in invitations if i.invited_by_id}
    names = (
        dict(db.execute(select(User.id, User.full_name).where(User.id.in_(ids))).all())
        if ids
        else {}
    )
    return [
        InvitationOut(
            id=i.id,
            email=i.email,
            role=i.role,
            invited_by_name=names.get(i.invited_by_id) if i.invited_by_id else None,
            created_at=i.created_at,
            expires_at=i.expires_at,
        )
        for i in invitations
    ]


def invite(db: Session, ctx: RequestContext, email: str, role: str) -> None:
    normalized = normalize_email(email)
    already = db.scalar(
        select(WorkspaceMember.id)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == ctx.workspace_id, User.email == normalized)
    )
    if already is not None:
        raise Conflict("Essa pessoa já é membro deste workspace.", code="already_member")
    now = utcnow()
    # Um convite pendente por e-mail: reenviar substitui o anterior.
    db.execute(
        update(WorkspaceInvitation)
        .where(
            WorkspaceInvitation.workspace_id == ctx.workspace_id,
            WorkspaceInvitation.email == normalized,
            WorkspaceInvitation.accepted_at.is_(None),
            WorkspaceInvitation.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    token = new_token()
    invitation = WorkspaceInvitation(
        workspace_id=ctx.workspace_id,
        email=normalized,
        role=role,
        token_hash=hash_token(token),
        invited_by_id=ctx.user.id,
        expires_at=now + timedelta(days=get_settings().invitation_ttl_days),
    )
    db.add(invitation)
    db.flush()
    workspace = db.get(Workspace, ctx.workspace_id)
    assert workspace is not None
    audit.record(
        db,
        "member.invited",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="invitation",
        entity_id=invitation.id,
        details={"role": role},
        ip=ctx.ip,
    )
    db.commit()
    enqueue_invitation_email(normalized, token, workspace.name, role)


def revoke_invitation(db: Session, ctx: RequestContext, invitation_id: uuid.UUID) -> None:
    invitation = db.scalar(
        select(WorkspaceInvitation).where(
            WorkspaceInvitation.id == invitation_id,
            WorkspaceInvitation.workspace_id == ctx.workspace_id,
            WorkspaceInvitation.accepted_at.is_(None),
            WorkspaceInvitation.revoked_at.is_(None),
        )
    )
    if invitation is None:
        raise NotFound("Convite não encontrado.")
    invitation.revoked_at = utcnow()
    audit.record(
        db,
        "member.invitation_revoked",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="invitation",
        entity_id=invitation.id,
        ip=ctx.ip,
    )
    db.commit()


def _usable(db: Session, token: str) -> WorkspaceInvitation:
    invitation = db.scalar(
        select(WorkspaceInvitation).where(WorkspaceInvitation.token_hash == hash_token(token))
    )
    if invitation is None or invitation.revoked_at is not None:
        raise NotFound("Convite inválido ou cancelado.", code="invitation_invalid")
    if invitation.accepted_at is not None:
        raise Gone("Este convite já foi usado.", code="invitation_used")
    if invitation.expires_at <= utcnow():
        raise Gone(
            "Este convite expirou. Peça um novo ao administrador.", code="invitation_expired"
        )
    return invitation


def preview_invitation(db: Session, token: str) -> InvitationPreview:
    invitation = _usable(db, token)
    workspace = db.get(Workspace, invitation.workspace_id)
    assert workspace is not None
    return InvitationPreview(
        workspace_name=workspace.name,
        role=invitation.role,
        email=invitation.email,
        expires_at=invitation.expires_at,
    )


def accept_invitation(
    db: Session, user: User, session: UserSession, token: str, *, ip: str | None
) -> uuid.UUID:
    invitation = _usable(db, token)
    if normalize_email(user.email) != invitation.email:
        raise Forbidden(
            "Este convite foi enviado para outro e-mail. Entre com a conta do e-mail convidado.",
            code="invitation_email_mismatch",
        )
    exists = db.scalar(
        select(WorkspaceMember.id).where(
            WorkspaceMember.workspace_id == invitation.workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if exists is None:
        db.add(
            WorkspaceMember(
                workspace_id=invitation.workspace_id, user_id=user.id, role=invitation.role
            )
        )
    invitation.accepted_at = utcnow()
    invitation.accepted_by_id = user.id
    session.active_workspace_id = invitation.workspace_id
    audit.record(
        db,
        "member.joined",
        workspace_id=invitation.workspace_id,
        actor_id=user.id,
        entity_type="invitation",
        entity_id=invitation.id,
        details={"role": invitation.role},
        ip=ip,
    )
    db.commit()
    return invitation.workspace_id


# ---------------------------------------------------------------- configurações


def get_settings_out(db: Session, workspace_id: uuid.UUID) -> WorkspaceSettingsOut:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise NotFound("Workspace não encontrado.")
    return WorkspaceSettingsOut(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        settings=WorkspaceSettings.model_validate(workspace.settings or {}),
    )


def update_workspace(
    db: Session, ctx: RequestContext, data: WorkspaceUpdate
) -> WorkspaceSettingsOut:
    workspace = db.get(Workspace, ctx.workspace_id)
    if workspace is None:
        raise NotFound("Workspace não encontrado.")
    if data.name is None and data.settings is None:
        raise ValidationFailed("Nada para alterar.")
    changed: dict[str, object] = {}
    if data.name is not None and data.name != workspace.name:
        changed["name"] = True
        workspace.name = data.name
    if data.settings is not None:
        before = WorkspaceSettings.model_validate(workspace.settings or {}).model_dump()
        after = data.settings.model_dump()
        changed.update(
            {k: {"from": before[k], "to": v} for k, v in after.items() if before[k] != v}
        )
        workspace.settings = after
    workspace.updated_at = utcnow()
    audit.record(
        db,
        "workspace.updated",
        workspace_id=ctx.workspace_id,
        actor_id=ctx.user.id,
        entity_type="workspace",
        entity_id=workspace.id,
        details={"changed": changed},
        ip=ctx.ip,
    )
    db.commit()
    return get_settings_out(db, ctx.workspace_id)
