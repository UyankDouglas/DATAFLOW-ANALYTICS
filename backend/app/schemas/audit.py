import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEntry(BaseModel):
    id: uuid.UUID
    action: str
    entity_type: str | None
    entity_id: str | None
    details: dict[str, Any]
    actor_id: uuid.UUID | None
    actor_name: str | None
    ip_address: str | None
    created_at: datetime
