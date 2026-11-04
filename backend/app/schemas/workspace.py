import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

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


class WorkspaceSettings(BaseModel):
    """Configurações do workspace, gravadas em `workspaces.settings`."""

    model_config = ConfigDict(extra="ignore")
    # Por quanto tempo um arquivo exportado pode ser baixado (depois é apagado).
    export_ttl_hours: int = Field(default=24, ge=1, le=168)
    # Visualizadores só exportam quando um administrador libera.
    viewer_exports: bool = False
    # Arquivos originais enviados são apagados após N dias (as versões publicadas ficam).
    # Nulo = guardar para sempre.
    original_retention_days: int | None = Field(default=None, ge=7, le=3650)


class WorkspaceSettingsOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    settings: WorkspaceSettings
    storage_used_bytes: int = 0
    storage_quota_bytes: int | None = None  # vazio = sem cota


class WorkspaceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=2, max_length=120)
    settings: WorkspaceSettings | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("o nome precisa de ao menos 2 caracteres")
        return cleaned


Role = Literal["admin", "analyst", "viewer"]


class MemberRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role


class InvitationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr = Field(max_length=255)
    role: Role


class InvitationOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    invited_by_name: str | None
    created_at: datetime
    expires_at: datetime


class InvitationToken(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=20, max_length=200)


class InvitationPreview(BaseModel):
    workspace_name: str
    role: str
    email: str
    expires_at: datetime
