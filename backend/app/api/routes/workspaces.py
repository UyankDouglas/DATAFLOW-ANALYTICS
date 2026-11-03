import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    AuthSession,
    RequestContext,
    client_ip,
    get_auth_session,
    get_context,
    get_db,
    require,
)
from app.core import rate_limit
from app.core.errors import NotFound
from app.core.permissions import Permission
from app.models import User, Workspace, WorkspaceMember
from app.schemas.common import Message
from app.schemas.workspace import (
    InvitationCreate,
    InvitationOut,
    InvitationPreview,
    InvitationToken,
    MemberOut,
    MemberRoleUpdate,
    SwitchWorkspaceRequest,
    WorkspaceOut,
    WorkspaceSettingsOut,
    WorkspaceSummary,
    WorkspaceUpdate,
)
from app.services import auth_service, members_service

INVITATIONS_PER_HOUR = 50

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
invitations = APIRouter(prefix="/invitations", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceSummary], summary="Workspaces do usuário")
def list_my_workspaces(
    auth: AuthSession = Depends(get_auth_session), db: Session = Depends(get_db)
) -> list[WorkspaceSummary]:
    rows = db.execute(
        select(Workspace, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == auth.user.id)
        .order_by(Workspace.name)
    ).all()
    return [WorkspaceSummary(id=w.id, name=w.name, slug=w.slug, role=role) for w, role in rows]


@router.get("/current", response_model=WorkspaceOut)
def current_workspace(
    ctx: RequestContext = Depends(get_context), db: Session = Depends(get_db)
) -> Workspace:
    workspace = db.get(Workspace, ctx.workspace_id)
    if workspace is None:
        raise NotFound("Workspace não encontrado.")
    return workspace


@router.get("/current/members", response_model=list[MemberOut])
def current_members(
    ctx: RequestContext = Depends(require(Permission.MEMBERS_VIEW)), db: Session = Depends(get_db)
) -> list[MemberOut]:
    rows = db.execute(
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == ctx.workspace_id)
        .order_by(User.full_name)
    ).all()
    return [
        MemberOut(
            id=m.id,
            user_id=u.id,
            full_name=u.full_name,
            email=u.email,
            role=m.role,
            joined_at=m.created_at,
        )
        for m, u in rows
    ]


@router.post("/switch", response_model=Message)
def switch_workspace(
    data: SwitchWorkspaceRequest,
    request: Request,
    auth: AuthSession = Depends(get_auth_session),
    db: Session = Depends(get_db),
) -> Message:
    auth_service.switch_workspace(db, auth.session, data.workspace_id, ip=client_ip(request))
    return Message(message="Workspace alterado.")


@router.get(
    "/current/settings",
    response_model=WorkspaceSettingsOut,
    summary="Nome e configurações do workspace (validade das exportações, retenção…)",
)
def workspace_settings(
    ctx: RequestContext = Depends(require(Permission.WORKSPACE_VIEW)),
    db: Session = Depends(get_db),
) -> WorkspaceSettingsOut:
    return members_service.get_settings_out(db, ctx.workspace_id)


@router.patch("/current", response_model=WorkspaceSettingsOut)
def update_workspace(
    data: WorkspaceUpdate,
    ctx: RequestContext = Depends(require(Permission.WORKSPACE_MANAGE)),
    db: Session = Depends(get_db),
) -> WorkspaceSettingsOut:
    return members_service.update_workspace(db, ctx, data)


@router.patch("/current/members/{member_id}", response_model=Message)
def change_member_role(
    member_id: uuid.UUID,
    data: MemberRoleUpdate,
    ctx: RequestContext = Depends(require(Permission.MEMBERS_MANAGE)),
    db: Session = Depends(get_db),
) -> Message:
    members_service.change_role(db, ctx, member_id, data.role)
    return Message(message="Perfil alterado.")


@router.delete("/current/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    member_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.MEMBERS_MANAGE)),
    db: Session = Depends(get_db),
) -> Response:
    members_service.remove_member(db, ctx, member_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/current/invitations", response_model=list[InvitationOut])
def list_invitations(
    ctx: RequestContext = Depends(require(Permission.MEMBERS_MANAGE)),
    db: Session = Depends(get_db),
) -> list[InvitationOut]:
    return members_service.list_invitations(db, ctx.workspace_id)


@router.post(
    "/current/invitations",
    response_model=Message,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Convida por e-mail (a pessoa entra ou se cadastra com esse e-mail para aceitar)",
)
def invite(
    data: InvitationCreate,
    ctx: RequestContext = Depends(require(Permission.MEMBERS_MANAGE)),
    db: Session = Depends(get_db),
) -> Message:
    rate_limit.hit("invite", str(ctx.workspace_id), limit=INVITATIONS_PER_HOUR, window_seconds=3600)
    members_service.invite(db, ctx, data.email, data.role)
    return Message(message="Convite enviado.")


@router.delete("/current/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invitation(
    invitation_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.MEMBERS_MANAGE)),
    db: Session = Depends(get_db),
) -> Response:
    members_service.revoke_invitation(db, ctx, invitation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@invitations.post("/preview", response_model=InvitationPreview, summary="Dados de um convite")
def preview_invitation(data: InvitationToken, db: Session = Depends(get_db)) -> InvitationPreview:
    return members_service.preview_invitation(db, data.token)


@invitations.post(
    "/accept",
    response_model=Message,
    summary="Aceita o convite com a conta logada (o e-mail precisa ser o convidado)",
)
def accept_invitation(
    data: InvitationToken,
    request: Request,
    auth: AuthSession = Depends(get_auth_session),
    db: Session = Depends(get_db),
) -> Message:
    members_service.accept_invitation(
        db, auth.user, auth.session, data.token, ip=client_ip(request)
    )
    return Message(message="Convite aceito.")
