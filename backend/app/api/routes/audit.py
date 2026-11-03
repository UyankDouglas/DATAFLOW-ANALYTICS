import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, get_db, require
from app.core.permissions import Permission
from app.schemas.audit import AuditEntry
from app.schemas.common import Page
from app.services import audit

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=Page[AuditEntry], summary="Registros de auditoria do workspace")
def search_audit(
    action: Annotated[str | None, Query(max_length=80, pattern=r"^[a-z_]+(\.[a-z_]+)?$")] = None,
    actor_id: uuid.UUID | None = None,
    entity_type: Annotated[str | None, Query(max_length=40, pattern=r"^[a-z_]+$")] = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    ctx: RequestContext = Depends(require(Permission.AUDIT_VIEW)),
    db: Session = Depends(get_db),
) -> Page[AuditEntry]:
    return audit.search(
        db,
        ctx.workspace_id,
        action=action,
        actor_id=actor_id,
        entity_type=entity_type,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )


@router.get("/actions", response_model=list[str], summary="Ações já registradas no workspace")
def audit_actions(
    ctx: RequestContext = Depends(require(Permission.AUDIT_VIEW)),
    db: Session = Depends(get_db),
) -> list[str]:
    return audit.actions(db, ctx.workspace_id)
