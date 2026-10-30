import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


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
