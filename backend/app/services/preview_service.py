"""Pré-visualização: primeiras linhas, tipos inferidos e estatísticas da amostra."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import NotFound, ServiceUnavailable, ValidationFailed
from app.models import Dataset, DatasetVersion, Upload
from app.processing.inference import ColumnInference, infer_columns
from app.processing.inspection import FileRejected, SampleTable, parse_sample
from app.processing.types import ParseOptions, normalize_column_name
from app.repositories import datasets as repo
from app.schemas.dataset import (
    ColumnPreview,
    DatasetColumnOut,
    PreviewResponse,
    RowCountInfo,
    UploadOut,
)
from app.services import storage


@dataclass
class SampleAnalysis:
    upload: Upload
    sample: SampleTable
    inferences: list[ColumnInference]


def read_sample(upload: Upload, options: ParseOptions) -> SampleAnalysis:
    settings = get_settings()
    length = min(settings.preview_sample_bytes, upload.size_bytes)
    try:
        data = storage.read_range(upload.storage_key, length)
    except storage.StorageError as exc:
        raise ServiceUnavailable("Não foi possível ler o arquivo armazenado agora.") from exc
    try:
        sample = parse_sample(
            data, options, truncated=upload.size_bytes > length, max_rows=settings.inference_rows
        )
    except FileRejected as exc:
        raise ValidationFailed(str(exc), code=exc.code) from exc
    if sample.column_count > settings.max_columns:
        raise ValidationFailed(
            f"O arquivo tem {sample.column_count} colunas; o limite é {settings.max_columns}.",
            code="too_many_columns",
        )
    return SampleAnalysis(upload, sample, infer_columns(sample.header, sample.rows, options))


def duplicate_names(names: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for name in names:
        key = normalize_column_name(name).casefold()
        if key in seen and name not in duplicates:
            duplicates.append(name)
        seen.setdefault(key, name)
    return duplicates


def _row_count(dataset: Dataset, upload: Upload, sample: SampleTable, db: Session) -> RowCountInfo:
    if dataset.current_version_id:
        version = db.get(DatasetVersion, dataset.current_version_id)
        if version is not None and version.upload_id == upload.id:
            return RowCountInfo(
                value=int(version.reconciliation.get("received", version.row_count)),
                exact=True,
                method="contagem do processamento concluído",
            )
    if sample.complete:
        return RowCountInfo(
            value=len(sample.rows) + sample.empty_rows,
            exact=True,
            method="arquivo lido por completo na pré-visualização",
        )
    lines = int(upload.detection.get("line_count", 0))
    estimate = max(lines - (1 if dataset.parse_options.get("has_header", True) else 0), 0)
    return RowCountInfo(value=estimate, exact=False, method="estimativa por quebras de linha")


def build_preview(
    db: Session, workspace_id: object, dataset_id: object, options: ParseOptions | None
) -> PreviewResponse:
    dataset = repo.get_dataset(db, workspace_id, dataset_id)  # type: ignore[arg-type]
    upload = repo.latest_upload(db, dataset.id)
    if upload is None:
        raise NotFound("Nenhum arquivo enviado para este dataset.")
    saved = ParseOptions.model_validate(dataset.parse_options)
    effective = options or saved
    analysis = read_sample(upload, effective)
    sample = analysis.sample
    settings = get_settings()

    warnings: list[str] = []
    if not upload.detection.get("utf8_valid", True):
        warnings.append(
            "O arquivo não é UTF-8 válido. Foi sugerido Windows-1252; confirme o encoding correto."
        )
    if sample.truncated:
        warnings.append(
            f"Estatísticas calculadas sobre uma amostra de {len(sample.rows)} registros do início do arquivo."
        )
    if sample.ragged_rows:
        warnings.append(
            f"{sample.ragged_rows} registro(s) da amostra têm quantidade de campos diferente do cabeçalho; "
            "serão rejeitados com motivo no processamento."
        )
    if any(i.ambiguous_formats for i in analysis.inferences):
        warnings.append(
            "Há colunas de data com formato ambíguo (dia/mês ou mês/dia). Confirme o formato."
        )

    suggested = ParseOptions(
        encoding=upload.detection.get("suggested_encoding", "utf-8"),
        delimiter=upload.detection.get("delimiter", ","),
        has_header=True,
        decimal_separator=upload.detection.get("decimal_separator", "."),
        thousands_separator=upload.detection.get("thousands_separator", ""),
    )
    return PreviewResponse(
        dataset_id=dataset.id,
        dataset_name=dataset.name,
        upload=UploadOut.model_validate(upload),
        parse_options=effective,
        suggested_options=suggested,
        header=sample.header,
        rows=[row[: sample.column_count] for row in sample.rows[: settings.preview_rows]],
        columns=[
            ColumnPreview(
                position=i.position,
                source_name=i.source_name,
                inferred_type=i.inferred_type,
                format=i.format,
                scale=i.scale,
                ambiguous_formats=i.ambiguous_formats,
                null_count=i.null_count,
                null_ratio=round(i.null_ratio, 4),
                distinct_count=i.distinct_count,
                is_empty=i.is_empty,
                warnings=i.warnings,
            )
            for i in analysis.inferences
        ],
        column_count=sample.column_count,
        row_count=_row_count(dataset, upload, sample, db),
        sample_rows_analyzed=len(sample.rows),
        sample_truncated=sample.truncated,
        ragged_rows_in_sample=sample.ragged_rows,
        empty_rows_in_sample=sample.empty_rows,
        duplicate_header_names=duplicate_names(sample.header),
        warnings=warnings,
        saved_columns=[DatasetColumnOut.model_validate(c) for c in dataset.columns],
    )
