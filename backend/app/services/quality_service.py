"""Relatórios de qualidade por versão, inconsistências e frequência de valores.

O relatório guarda só contagens e estatísticas agregadas no PostgreSQL. Valores de registros
(valor original de uma inconsistência, frequência de valores) são lidos do Parquet sob demanda,
depois da checagem de workspace.
"""

import logging
import uuid
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.cache import local_parquet
from app.analytics.quality import FORMULA_VERSION, compute_quality
from app.analytics.query import (
    query_connection,
    quote_identifier,
    run_limited,
    to_json_value,
)
from app.core.errors import NotFound, ServiceUnavailable, ValidationFailed
from app.models import DatasetVersion, QualityIssue, QualityReport, User
from app.models.base import utcnow
from app.processing.transforms import RULE_LABELS
from app.repositories import datasets as repo
from app.schemas.quality import (
    InconsistencyPage,
    InconsistencyRow,
    QualityIssueOut,
    QualityReportOut,
    QualityVersionSummary,
    ValueCount,
    ValueFrequency,
)

logger = logging.getLogger(__name__)

MAX_ISSUE_GROUPS = 500
_META = {
    "__df_row",
    "__df_line",
    "__df_reason",
    "__df_column",
    "__df_detail",
    "__df_category",
    "__df_rule",
    "__df_duplicate_of",
}
TREATMENT = {
    "rejeitado": "Excluído da versão; valor original preservado",
    "filtrado": "Removido pelo filtro configurado",
    "duplicado": "Removido como duplicado",
}


def rule_label(version: DatasetVersion, rule: int | None) -> str:
    """Regra que excluiu o registro: posição no conjunto aplicado ou a leitura do arquivo."""
    if rule is None:
        return "Leitura e mapeamento do arquivo"
    steps = version.transformations.get("steps") or []
    if 1 <= rule <= len(steps):
        operation = steps[rule - 1].get("operation", "")
        return f"Regra {rule}: {RULE_LABELS.get(operation, operation)}"
    return f"Regra {rule}"


# ---------------------------------------------------------------- cálculo


def build_report(
    db: Session,
    version: DatasetVersion,
    data_path: Path,
    rejected_path: Path | None,
    actor_id: uuid.UUID | None,
) -> QualityReport:
    """Calcula e grava (ou substitui) o relatório da versão. Não faz commit."""
    result = compute_quality(
        data_path, rejected_path, version.column_schema, version.reconciliation
    )
    report = db.scalar(select(QualityReport).where(QualityReport.version_id == version.id))
    if report is None:
        report = QualityReport(
            workspace_id=version.workspace_id,
            dataset_id=version.dataset_id,
            version_id=version.id,
        )
        db.add(report)
    report.formula_version = FORMULA_VERSION
    report.score = result.score
    report.metrics = {**result.metrics, "issue_groups_total": len(result.issues)}
    report.computed_by_id = actor_id
    report.duration_ms = result.duration_ms
    report.updated_at = utcnow()
    report.issues.clear()
    db.flush()
    for issue in result.issues[:MAX_ISSUE_GROUPS]:
        report.issues.append(
            QualityIssue(
                category=issue.category,
                reason=issue.reason,
                column_name=issue.column,
                rule=issue.rule,
                count=issue.count,
                example_row=issue.example_row,
            )
        )
    db.flush()
    return report


def _local_paths(version: DatasetVersion) -> tuple[Path, Path | None]:
    data = local_parquet(f"v-{version.id}", version.storage_key, version.checksum_sha256)
    rejected = (
        local_parquet(f"r-{version.id}", version.rejected_storage_key)
        if version.rejected_storage_key
        else None
    )
    return data, rejected


def compute_for_version(
    db: Session,
    workspace_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> QualityReport:
    version = repo.get_version(db, workspace_id, dataset_id, version_id)
    data, rejected = _local_paths(version)
    try:
        report = build_report(db, version, data, rejected, actor_id)
    except duckdb.Error as exc:
        raise ServiceUnavailable("Não foi possível calcular a qualidade agora.") from exc
    db.commit()
    return report


# ---------------------------------------------------------------- leitura


def _report_out(db: Session, report: QualityReport, version: DatasetVersion) -> QualityReportOut:
    name = db.scalar(select(User.full_name).where(User.id == report.computed_by_id))
    return QualityReportOut(
        id=report.id,
        dataset_id=report.dataset_id,
        version_id=report.version_id,
        version_number=version.version_number,
        formula_version=report.formula_version,
        score=report.score,
        metrics=report.metrics,
        issues=[
            QualityIssueOut(
                category=i.category,
                reason=i.reason,
                column=i.column_name,
                rule=i.rule,
                rule_label=rule_label(version, i.rule),
                count=i.count,
                example_row=i.example_row,
            )
            for i in report.issues
        ],
        computed_by_name=name,
        computed_at=report.updated_at,
        duration_ms=report.duration_ms,
    )


def get_report(
    db: Session, workspace_id: uuid.UUID, dataset_id: uuid.UUID, version_id: uuid.UUID
) -> QualityReportOut:
    version = repo.get_version(db, workspace_id, dataset_id, version_id)
    report = db.scalar(select(QualityReport).where(QualityReport.version_id == version.id))
    if report is None:
        raise NotFound(
            "O relatório de qualidade desta versão ainda não foi calculado.",
            code="quality_not_computed",
        )
    return _report_out(db, report, version)


def report_out_for(db: Session, report: QualityReport) -> QualityReportOut:
    version = db.get(DatasetVersion, report.version_id)
    assert version is not None
    return _report_out(db, report, version)


def compare_versions(
    db: Session, workspace_id: uuid.UUID, dataset_id: uuid.UUID
) -> list[QualityVersionSummary]:
    repo.get_dataset(db, workspace_id, dataset_id)
    rows = db.execute(
        select(DatasetVersion, QualityReport)
        .outerjoin(QualityReport, QualityReport.version_id == DatasetVersion.id)
        .where(DatasetVersion.dataset_id == dataset_id, DatasetVersion.workspace_id == workspace_id)
        .order_by(DatasetVersion.version_number)
    ).all()
    numbers = {version.id: version.version_number for version, _ in rows}
    items = []
    for version, report in rows:
        item = QualityVersionSummary(
            version_id=version.id,
            version_number=version.version_number,
            parent_version_number=numbers.get(version.parent_version_id)
            if version.parent_version_id
            else None,
            kind=str(version.transformations.get("kind", "import")),
            created_at=version.created_at,
            computed=report is not None,
        )
        if report is not None:
            item.score = report.score
            item.indicators = report.metrics.get("indicators", {})
            item.components = report.metrics.get("components", {})
        items.append(item)
    return items


def inconsistencies(
    db: Session,
    workspace_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    category: str | None,
    reason: str | None,
    column: str | None,
    page: int,
    page_size: int,
) -> InconsistencyPage:
    """Registros excluídos com motivo, regra e tratamento, filtráveis e paginados no servidor."""
    version = repo.get_version(db, workspace_id, dataset_id, version_id)
    empty = InconsistencyPage(
        version_id=version.id, items=[], total=0, page=page, page_size=page_size
    )
    if not version.rejected_storage_key:
        return empty
    path = local_parquet(f"r-{version.id}", version.rejected_storage_key)
    names = pq.read_schema(path).names
    inputs = [n for n in names if n not in _META]
    has_category = "__df_category" in names
    category_sql = "__df_category" if has_category else "'rejeitado'"

    conditions: list[str] = []
    params: dict[str, Any] = {"path": str(path)}
    if category:
        conditions.append(f"{category_sql} = $category")
        params["category"] = category
    if reason:
        conditions.append("__df_reason = $reason")
        params["reason"] = reason
    if column:
        conditions.append("__df_column = $column")
        params["column"] = column
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    rule_sql = "__df_rule" if "__df_rule" in names else "NULL::INTEGER"
    duplicate_sql = "__df_duplicate_of" if "__df_duplicate_of" in names else "NULL::BIGINT"
    select_inputs = "".join(f", {quote_identifier(n)}" for n in inputs)
    try:
        with query_connection(path.parent) as con:
            total = int(
                run_limited(con, f"SELECT count(*) FROM read_parquet($path){where}", params)[0][0]  # noqa: S608
            )
            found = run_limited(
                con,
                f"SELECT __df_row, __df_line, {category_sql}, __df_reason, __df_column, "  # noqa: S608
                f"{rule_sql}, {duplicate_sql}, __df_detail{select_inputs} "
                f"FROM read_parquet($path){where} ORDER BY __df_row LIMIT $limit OFFSET $offset",
                {**params, "limit": page_size, "offset": (page - 1) * page_size},
            )
    except duckdb.Error as exc:
        raise ServiceUnavailable("Não foi possível consultar as inconsistências agora.") from exc

    items = []
    for row in found:
        row_no, line, cat, why, col, rule, duplicate_of, detail, *values = row
        record = dict(zip(inputs, values, strict=True))
        treatment = TREATMENT.get(str(cat), "Excluído da versão")
        if cat == "duplicado" and duplicate_of is not None:
            treatment = f"Removido como duplicado; mantido o registro {duplicate_of}"
        items.append(
            InconsistencyRow(
                row=int(row_no),
                line=int(line) if line is not None else None,
                category=str(cat),
                reason=str(why),
                column=col,
                original_value=record.get(col) if col else None,
                rule=int(rule) if rule is not None else None,
                rule_label=rule_label(version, int(rule) if rule is not None else None),
                treatment=treatment,
                detail=detail,
                duplicate_of=int(duplicate_of) if duplicate_of is not None else None,
                record=record,
            )
        )
    return InconsistencyPage(
        version_id=version.id, items=items, total=total, page=page, page_size=page_size
    )


def value_frequency(
    db: Session,
    workspace_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID,
    column: str,
    limit: int,
) -> ValueFrequency:
    """Valores mais frequentes de uma coluna da versão (lidos do Parquet, não do banco)."""
    version = repo.get_version(db, workspace_id, dataset_id, version_id)
    spec = next((c for c in version.column_schema if c["name"] == column), None)
    if spec is None:
        raise ValidationFailed("Coluna desconhecida nesta versão.", details={"column": column})
    path = local_parquet(f"v-{version.id}", version.storage_key, version.checksum_sha256)
    name = quote_identifier(column)
    try:
        with query_connection(path.parent) as con:
            totals = run_limited(
                con,
                f"SELECT count(*), count({name}), count(DISTINCT {name}) FROM read_parquet($path)",  # noqa: S608
                {"path": str(path)},
            )[0]
            top = run_limited(
                con,
                f"SELECT {name}, count(*) AS n FROM read_parquet($path) WHERE {name} IS NOT NULL "  # noqa: S608
                f"GROUP BY {name} ORDER BY n DESC, {name} LIMIT $limit",
                {"path": str(path), "limit": limit},
            )
    except duckdb.Error as exc:
        raise ServiceUnavailable("Não foi possível calcular a frequência agora.") from exc
    total, non_null, distinct = (int(v) for v in totals)
    values = [ValueCount(value=to_json_value(v), count=int(n)) for v, n in top]
    return ValueFrequency(
        column=column,
        data_type=spec["data_type"],
        total=total,
        nulls=total - non_null,
        distinct=distinct,
        values=values,
        others=non_null - sum(v.count for v in values),
    )
