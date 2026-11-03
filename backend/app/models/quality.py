import uuid
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey

ISSUE_CATEGORIES = ("rejeitado", "filtrado", "duplicado")


class QualityReport(UUIDPrimaryKey, Timestamps, Base):
    """Relatório de qualidade de uma versão publicada (uma por versão; recalculável).

    Guarda só contagens e estatísticas agregadas: valores dos registros ficam no Parquet
    e são lidos sob demanda, com autorização.
    """

    __tablename__ = "quality_reports"
    __table_args__ = (
        CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="score_range"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="CASCADE"), unique=True
    )
    formula_version: Mapped[str] = mapped_column(String(10))
    # Nota de 0 a 100; nula quando não há registros publicáveis para avaliar.
    score: Mapped[float | None]
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)
    computed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    duration_ms: Mapped[int] = mapped_column(default=0)

    issues: Mapped[list["QualityIssue"]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="QualityIssue.count.desc()",
    )


class QualityIssue(UUIDPrimaryKey, Base):
    """Grupo de exclusões de mesmo tipo: categoria, motivo, coluna e regra."""

    __tablename__ = "quality_issues"
    __table_args__ = (
        CheckConstraint(
            "category IN (" + ", ".join(f"'{c}'" for c in ISSUE_CATEGORIES) + ")",
            name="category_valid",
        ),
        CheckConstraint("count > 0", name="count_positive"),
    )

    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quality_reports.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(60))
    column_name: Mapped[str | None] = mapped_column(String(120))
    rule: Mapped[int | None]  # posição 1-based da regra de transformação, quando houver
    count: Mapped[int] = mapped_column(BigInteger)
    example_row: Mapped[int | None] = mapped_column(BigInteger)

    report: Mapped[QualityReport] = relationship(back_populates="issues")
