"""Pré-visualização: primeiras linhas, tipos inferidos e estatísticas da amostra."""

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.cache import local_file
from app.core.config import get_settings
from app.core.errors import Gone, NotFound, ServiceUnavailable, ValidationFailed
from app.models import Dataset, DatasetVersion, Upload
from app.processing.inference import ColumnInference, infer_columns
from app.processing.inspection import FileRejected, SampleTable, parse_sample
from app.processing.types import ParseOptions, normalize_column_name
from app.processing.xlsx import XlsxSample, parse_xlsx_sample
from app.repositories import datasets as repo
from app.schemas.dataset import (
    ColumnPreview,
    DatasetColumnOut,
    PreviewResponse,
    RowCountInfo,
    SheetInfo,
    UploadOut,
)
from app.services import storage


@dataclass
class SampleAnalysis:
    upload: Upload
    sample: SampleTable
    inferences: list[ColumnInference]
    options: ParseOptions  # opções efetivas (no XLSX, com a linha do cabeçalho resolvida)
    xlsx: XlsxSample | None = None


def ensure_original(upload: Upload) -> None:
    """O original pode ter sido apagado pela política de retenção; as versões continuam."""
    if upload.purged_at is not None:
        raise Gone(
            "O arquivo original foi apagado pela política de retenção do workspace. As versões "
            "publicadas continuam disponíveis; para reprocessar do zero, envie o arquivo de novo.",
            code="original_purged",
        )


def local_upload(upload: Upload) -> Path:
    """Cópia local do arquivo enviado (XLSX precisa do arquivo inteiro para ser aberto)."""
    return local_file(f"u-{upload.id}", upload.storage_key, upload.sha256, suffix=".xlsx")


def _read_csv(upload: Upload, options: ParseOptions) -> SampleTable:
    settings = get_settings()
    length = min(settings.preview_sample_bytes, upload.size_bytes)
    try:
        data = storage.read_range(upload.storage_key, length)
    except storage.StorageError as exc:
        raise ServiceUnavailable("Não foi possível ler o arquivo armazenado agora.") from exc
    return parse_sample(
        data, options, truncated=upload.size_bytes > length, max_rows=settings.inference_rows
    )


def read_sample(upload: Upload, options: ParseOptions) -> SampleAnalysis:
    ensure_original(upload)
    settings = get_settings()
    xlsx: XlsxSample | None = None
    try:
        if upload.file_format == "xlsx":
            xlsx = parse_xlsx_sample(local_upload(upload), options, settings.inference_rows)
            sample = xlsx.table
            options = options.model_copy(
                update={"sheet": xlsx.sheet, "header_row": xlsx.layout.header_row}
            )
        else:
            sample = _read_csv(upload, options)
    except FileRejected as exc:
        raise ValidationFailed(str(exc), code=exc.code) from exc
    if sample.column_count > settings.max_columns:
        raise ValidationFailed(
            f"O arquivo tem {sample.column_count} colunas; o limite é {settings.max_columns}.",
            code="too_many_columns",
        )
    inferences = infer_columns(sample.header, sample.rows, options)
    return SampleAnalysis(upload, sample, inferences, options, xlsx)


def duplicate_names(names: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for name in names:
        key = normalize_column_name(name).casefold()
        if key in seen and name not in duplicates:
            duplicates.append(name)
        seen.setdefault(key, name)
    return duplicates


def _row_count(
    dataset: Dataset, analysis: SampleAnalysis, options: ParseOptions, db: Session
) -> RowCountInfo:
    upload, sample = analysis.upload, analysis.sample
    # Última importação deste mesmo arquivo com a mesma leitura (versões transformadas não contam).
    imported = db.scalar(
        select(DatasetVersion)
        .where(
            DatasetVersion.dataset_id == dataset.id,
            DatasetVersion.upload_id == upload.id,
            DatasetVersion.parent_version_id.is_(None),
        )
        .order_by(DatasetVersion.version_number.desc())
        .limit(1)
    )
    if (
        imported is not None
        and imported.transformations.get("parse_options") == options.model_dump()
    ):
        return RowCountInfo(
            value=int(imported.reconciliation.get("received", imported.row_count)),
            exact=True,
            method="contagem do processamento concluído",
        )
    if sample.complete:
        return RowCountInfo(
            value=len(sample.rows) + sample.empty_rows,
            exact=True,
            method="arquivo lido por completo na pré-visualização",
        )
    if analysis.xlsx is not None:
        return RowCountInfo(
            value=analysis.xlsx.estimated_rows or len(sample.rows),
            exact=False,
            method="estimativa pela dimensão declarada na aba",
        )
    lines = int(upload.detection.get("line_count", 0))
    estimate = max(lines - (1 if options.has_header else 0), 0)
    return RowCountInfo(value=estimate, exact=False, method="estimativa por quebras de linha")


def build_preview(
    db: Session, workspace_id: object, dataset_id: object, options: ParseOptions | None
) -> PreviewResponse:
    dataset = repo.get_dataset(db, workspace_id, dataset_id)  # type: ignore[arg-type]
    upload = repo.latest_upload(db, dataset.id)
    if upload is None:
        raise NotFound("Nenhum arquivo enviado para este dataset.")
    saved = ParseOptions.model_validate(dataset.parse_options)
    analysis = read_sample(upload, options or saved)
    effective = analysis.options
    sample = analysis.sample
    xlsx = analysis.xlsx
    settings = get_settings()

    warnings: list[str] = []
    if xlsx is None and not upload.detection.get("utf8_valid", True):
        warnings.append(
            "O arquivo não é UTF-8 válido. Foi sugerido Windows-1252; confirme o encoding correto."
        )
    if xlsx is not None:
        selected = next((s for s in xlsx.sheets if s["name"] == effective.sheet), None)
        if selected is not None and selected["hidden"]:
            warnings.append("A aba selecionada está oculta na planilha.")
        if xlsx.cell_issues:
            warnings.append(
                f"{xlsx.cell_issues} registro(s) da amostra têm fórmula sem valor calculado ou erro "
                "de célula (#DIV/0!, #N/D...). Fórmulas não são executadas: esses registros serão "
                "rejeitados com motivo."
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

    if xlsx is not None:
        suggested = ParseOptions(sheet=effective.sheet, header_row=xlsx.layout.header_row)
    else:
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
        row_count=_row_count(dataset, analysis, effective, db),
        sample_rows_analyzed=len(sample.rows),
        sample_truncated=sample.truncated,
        ragged_rows_in_sample=sample.ragged_rows,
        empty_rows_in_sample=sample.empty_rows,
        duplicate_header_names=duplicate_names(sample.header),
        warnings=warnings,
        saved_columns=[DatasetColumnOut.model_validate(c) for c in dataset.columns],
        source_format=upload.file_format,
        sheets=[SheetInfo.model_validate(s) for s in xlsx.sheets] if xlsx else [],
        data_range=xlsx.data_range if xlsx else None,
        first_column=xlsx.layout.first_column if xlsx else None,
        cell_issues_in_sample=xlsx.cell_issues if xlsx else 0,
    )
