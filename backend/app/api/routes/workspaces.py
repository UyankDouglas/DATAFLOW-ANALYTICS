from fastapi import APIRouter, Depends, Request
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
from app.core.errors import NotFound
from app.core.permissions import Permission
from app.models import User, Workspace, WorkspaceMember
from app.schemas.common import Message
from app.schemas.workspace import MemberOut, SwitchWorkspaceRequest, WorkspaceOut, WorkspaceSummary
from app.services import auth_service

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


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
