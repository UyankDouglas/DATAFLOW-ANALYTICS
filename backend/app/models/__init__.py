"""Modelos ORM. Importar este pacote registra todas as tabelas no metadata."""

from app.models.audit import AuditLog
from app.models.base import Base
from app.models.dataset import Dataset, DatasetColumn, DatasetStatus, DatasetVersion
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
from app.models.workspace import Role, Workspace, WorkspaceMember

__all__ = [
    "RUNNING_STATUSES",
    "TERMINAL_STATUSES",
    "AuditLog",
    "Base",
    "Dataset",
    "DatasetColumn",
    "DatasetStatus",
    "DatasetVersion",
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
    "WorkspaceMember",
]
