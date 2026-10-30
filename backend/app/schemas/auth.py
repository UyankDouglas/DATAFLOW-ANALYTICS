import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import APIModel

PASSWORD_MIN = 10
PASSWORD_MAX = 128


def _check_password(value: str) -> str:
    if len(value) < PASSWORD_MIN:
        raise ValueError(f"a senha precisa ter ao menos {PASSWORD_MIN} caracteres")
    if len(value) > PASSWORD_MAX:
        raise ValueError(f"a senha pode ter no máximo {PASSWORD_MAX} caracteres")
    if len(set(value)) < 4:
        raise ValueError("a senha é repetitiva demais")
    return value


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str
    workspace_name: str = Field(min_length=2, max_length=120)

    _password = field_validator("password")(_check_password)

    @field_validator("full_name", "workspace_name")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("informe ao menos 2 caracteres")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=PASSWORD_MAX)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str

    _password = field_validator("password")(_check_password)


class UserOut(APIModel):
    id: uuid.UUID
    email: str
    full_name: str
    created_at: datetime


class WorkspaceRef(APIModel):
    id: uuid.UUID
    name: str
    slug: str
    role: str


class MeResponse(BaseModel):
    user: UserOut
    workspace: WorkspaceRef | None
    permissions: list[str]
    csrf_token: str


class CsrfResponse(BaseModel):
    csrf_token: str
