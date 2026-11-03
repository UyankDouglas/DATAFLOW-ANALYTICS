import datetime as dt
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, User
from app.schemas.audit import AuditEntry
from app.schemas.common import Page


def record(
    db: Session,
    action: str,
    *,
    workspace_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: object | None = None,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """Adiciona um registro de auditoria na transação corrente (commit fica com o chamador)."""
    db.add(
        AuditLog(
            workspace_id=workspace_id,
            actor_user_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            details=details or {},
            ip_address=ip,
        )
    )


def search(
    db: Session,
    workspace_id: uuid.UUID,
    *,
    action: str | None,
    actor_id: uuid.UUID | None,
    entity_type: str | None,
    date_from: dt.date | None,
    date_to: dt.date | None,
    page: int,
    page_size: int,
) -> Page[AuditEntry]:
    """Registros do workspace, do mais recente ao mais antigo. `action` aceita a ação exata
    ("export.downloaded") ou só a categoria ("export"). Datas inclusivas, em UTC."""
    conditions = [AuditLog.workspace_id == workspace_id]
    if action:
        conditions.append(
            AuditLog.action == action if "." in action else AuditLog.action.startswith(f"{action}.")
        )
    if actor_id is not None:
        conditions.append(AuditLog.actor_user_id == actor_id)
    if entity_type:
        conditions.append(AuditLog.entity_type == entity_type)
    if date_from is not None:
        conditions.append(
            AuditLog.created_at >= dt.datetime.combine(date_from, dt.time.min, tzinfo=dt.UTC)
        )
    if date_to is not None:
        conditions.append(
            AuditLog.created_at
            < dt.datetime.combine(date_to + dt.timedelta(days=1), dt.time.min, tzinfo=dt.UTC)
        )
    total = db.scalar(select(func.count()).select_from(AuditLog).where(*conditions)) or 0
    rows = db.execute(
        select(AuditLog, User.full_name)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .where(*conditions)
        .order_by(AuditLog.created_at.desc(), AuditLog.id)
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    return Page(
        items=[
            AuditEntry(
                id=log.id,
                action=log.action,
                entity_type=log.entity_type,
                entity_id=log.entity_id,
                details=log.details or {},
                actor_id=log.actor_user_id,
                actor_name=name,
                ip_address=log.ip_address,
                created_at=log.created_at,
            )
            for log, name in rows
        ],
        total=int(total),
        page=page,
        page_size=page_size,
    )


def actions(db: Session, workspace_id: uuid.UUID) -> list[str]:
    return list(
        db.scalars(
            select(AuditLog.action)
            .where(AuditLog.workspace_id == workspace_id)
            .distinct()
            .order_by(AuditLog.action)
        ).all()
    )
