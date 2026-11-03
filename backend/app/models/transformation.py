import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey

OPERATIONS = (
    "trim",
    "normalize_text",
    "change_case",
    "convert_type",
    "standardize_dates",
    "fix_numbers",
    "handle_nulls",
    "remove_empty_rows",
    "filter_rows",
    "rename_columns",
    "derived_column",
    "deduplicate",
)


class TransformationSet(UUIDPrimaryKey, Timestamps, Base):
    """Conjunto reutilizável de regras de um dataset. A revisão sobe a cada alteração;
    jobs guardam uma cópia das regras, então editar o conjunto não muda versões passadas."""

    __tablename__ = "transformation_sets"
    __table_args__ = (UniqueConstraint("dataset_id", "name"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(default=1)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    rules: Mapped[list["TransformationRule"]] = relationship(
        back_populates="transformation_set",
        cascade="all, delete-orphan",
        order_by="TransformationRule.position",
    )


class TransformationRule(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "transformation_rules"
    __table_args__ = (
        UniqueConstraint("set_id", "position"),
        CheckConstraint(
            "operation IN (" + ", ".join(f"'{op}'" for op in OPERATIONS) + ")",
            name="operation_valid",
        ),
    )

    set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transformation_sets.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    operation: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[bool] = mapped_column(default=True, server_default=true())
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)

    transformation_set: Mapped[TransformationSet] = relationship(back_populates="rules")
