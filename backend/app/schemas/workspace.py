import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import APIModel


class WorkspaceOut(APIModel):
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime


class WorkspaceSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    role: str


class MemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    email: str
    role: str
    joined_at: datetime


class SwitchWorkspaceRequest(BaseModel):
    workspace_id: uuid.UUID
