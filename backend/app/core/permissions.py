"""RBAC: cada perfil recebe um conjunto explícito de permissões verificadas no backend."""

from enum import StrEnum

from app.models.workspace import Role


class Permission(StrEnum):
    WORKSPACE_VIEW = "workspace:view"
    WORKSPACE_MANAGE = "workspace:manage"
    MEMBERS_VIEW = "members:view"
    MEMBERS_MANAGE = "members:manage"
    DATASETS_VIEW = "datasets:view"
    DATASETS_UPLOAD = "datasets:upload"
    DATASETS_PROCESS = "datasets:process"
    DATASETS_DELETE = "datasets:delete"
    JOBS_VIEW = "jobs:view"
    JOBS_CANCEL = "jobs:cancel"
    DATA_EXPORT = "data:export"
    AUDIT_VIEW = "audit:view"


_VIEWER = {
    Permission.WORKSPACE_VIEW,
    Permission.DATASETS_VIEW,
    Permission.JOBS_VIEW,
}
_ANALYST = _VIEWER | {
    Permission.MEMBERS_VIEW,
    Permission.DATASETS_UPLOAD,
    Permission.DATASETS_PROCESS,
    Permission.JOBS_CANCEL,
    Permission.DATA_EXPORT,
}
_ADMIN = set(Permission)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset(_VIEWER),
    Role.ANALYST: frozenset(_ANALYST),
    Role.ADMIN: frozenset(_ADMIN),
}


def permissions_for(role: str) -> frozenset[Permission]:
    try:
        return ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return frozenset()
