"""Modelos ORM. Importar este pacote registra todas as tabelas no metadata."""

from app.models.audit import AuditLog
from app.models.base import Base
from app.models.dashboard import Dashboard, DashboardWidget
from app.models.dataset import Dataset, DatasetColumn, DatasetStatus, DatasetVersion
from app.models.export import ACTIVE_EXPORT_STATUSES, ExportJob, ExportStatus
from app.models.job import (
    RUNNING_STATUSES,
    TERMINAL_STATUSES,
    JobKind,
    JobStatus,
    ProcessingJob,
)
from app.models.quality import QualityIssue, QualityReport
from app.models.transformation import TransformationRule, TransformationSet
from app.models.upload import Upload
from app.models.user import PasswordResetToken, User, UserSession
from app.models.workspace import Role, Workspace, WorkspaceInvitation, WorkspaceMember

__all__ = [
    "ACTIVE_EXPORT_STATUSES",
    "RUNNING_STATUSES",
    "TERMINAL_STATUSES",
    "AuditLog",
    "Base",
    "Dashboard",
    "DashboardWidget",
    "Dataset",
    "DatasetColumn",
    "DatasetStatus",
    "DatasetVersion",
    "ExportJob",
    "ExportStatus",
    "JobKind",
    "JobStatus",
    "PasswordResetToken",
    "ProcessingJob",
    "QualityIssue",
    "QualityReport",
    "Role",
    "TransformationRule",
    "TransformationSet",
    "Upload",
    "User",
    "UserSession",
    "Workspace",
    "WorkspaceInvitation",
    "WorkspaceMember",
]
