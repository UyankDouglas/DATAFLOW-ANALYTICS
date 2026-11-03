import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey

CHART_TYPES = ("kpi", "line", "bar", "bar_horizontal", "area", "pie", "donut", "table")
WIDGET_SIZES = ("small", "medium", "large")


class Dashboard(UUIDPrimaryKey, Timestamps, Base):
    """Dashboard salvo: dataset, versão (fixa ou sempre a atual), filtros gerais e widgets.

    Não guarda resultados: cada widget é recalculado pela API a partir do Parquet da versão.
    """

    __tablename__ = "dashboards"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    # Nulo = acompanha a versão atual do dataset. Uma versão fixada não pode ser excluída
    # enquanto houver dashboard apontando para ela (sem ON DELETE).
    version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("dataset_versions.id"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    # Filtros aplicados a todos os widgets: {"filters": [...], "match": "all" | "any"}.
    filters: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    widgets: Mapped[list["DashboardWidget"]] = relationship(
        back_populates="dashboard",
        cascade="all, delete-orphan",
        order_by="DashboardWidget.position",
    )


class DashboardWidget(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "dashboard_widgets"
    __table_args__ = (
        UniqueConstraint("dashboard_id", "position"),
        CheckConstraint(
            "chart_type IN (" + ", ".join(f"'{t}'" for t in CHART_TYPES) + ")",
            name="chart_type_valid",
        ),
        CheckConstraint(
            "size IN (" + ", ".join(f"'{s}'" for s in WIDGET_SIZES) + ")", name="size_valid"
        ),
    )

    dashboard_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dashboards.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    title: Mapped[str] = mapped_column(String(120))
    chart_type: Mapped[str] = mapped_column(String(20))
    size: Mapped[str] = mapped_column(String(10), default="medium")
    # Consulta do widget (medidas, dimensão, filtros, ordenação, comparação), validada pelo
    # mesmo modelo das consultas analíticas antes de ser gravada.
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)

    dashboard: Mapped[Dashboard] = relationship(back_populates="widgets")
