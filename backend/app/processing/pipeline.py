"""Pipeline de importação CSV → Parquet, sem dependência de banco ou armazenamento.

O orquestrador (services/job_runner.py) cuida de estado, cancelamento e publicação; este
módulo apenas transforma arquivos locais e reporta progresso real a cada lote.
"""

import hashlib
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.processing.convert import META_COLUMNS, convert_batch
from app.processing.reader import read_batches
from app.processing.types import DECIMAL_PRECISION, ColumnConfig, DataType, ParseOptions

MAX_SAMPLES = 200


@dataclass
class Progress:
    rows_processed: int
    bytes_processed: int
    bytes_total: int


@dataclass
class PipelineResult:
    rows_total: int = 0
    rows_valid: int = 0
    rows_rejected: int = 0
    reasons: Counter[str] = field(default_factory=Counter)
    column_failures: Counter[str] = field(default_factory=Counter)
    null_counts: Counter[str] = field(default_factory=Counter)
    samples: list[dict[str, Any]] = field(default_factory=list)
    data_path: Path | None = None
    rejected_path: Path | None = None
    timings_ms: dict[str, int] = field(default_factory=dict)

    @property
    def reconciliation(self) -> dict[str, Any]:
        return {
            "received": self.rows_total,
            "valid": self.rows_valid,
            "rejected": self.rows_rejected,
            # A deduplicação chega na Fase 2; registrado explicitamente como não aplicada.
            "duplicates": None,
            "duplicates_policy": "nao_aplicada",
            "consistent": self.rows_total == self.rows_valid + self.rows_rejected,
        }


def arrow_type(column: ColumnConfig) -> pa.DataType:
    match column.data_type:
        case DataType.TEXT:
            return pa.string()
        case DataType.INTEGER:
            return pa.int64()
        case DataType.DECIMAL:
            return pa.decimal128(DECIMAL_PRECISION, column.scale or 0)
        case DataType.DATE:
            return pa.date32()
        case DataType.DATETIME:
            return pa.timestamp("us")
        case DataType.BOOLEAN:
            return pa.bool_()


def data_schema(columns: list[ColumnConfig]) -> pa.Schema:
    fields = [pa.field("__df_row", pa.int64(), nullable=False)]
    fields += [pa.field(c.name, arrow_type(c)) for c in columns]
    return pa.schema(fields)


def rejected_schema(columns: list[ColumnConfig]) -> pa.Schema:
    fields = [
        pa.field("__df_row", pa.int64()),
        pa.field("__df_line", pa.int64()),
        pa.field("__df_reason", pa.string()),
        pa.field("__df_column", pa.string()),
        pa.field("__df_detail", pa.string()),
    ]
    fields += [pa.field(c.name, pa.string()) for c in columns]
    return pa.schema(fields)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_csv_pipeline(
    source: Path,
    out_dir: Path,
    options: ParseOptions,
    columns: list[ColumnConfig],
    expected_header: list[str] | None,
    *,
    batch_rows: int,
    max_field_bytes: int,
    on_progress: Callable[[Progress], None],
) -> PipelineResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    result = PipelineResult()
    bytes_total = source.stat().st_size
    data_path = out_dir / "data.parquet"
    rejected_path = out_dir / "rejected.parquet"
    valid_schema = data_schema(columns)
    reject_schema = rejected_schema(columns)
    timings = Counter[str]()

    writer = pq.ParquetWriter(data_path, valid_schema, compression="zstd")
    rejected_writer: pq.ParquetWriter | None = None
    try:
        started = time.perf_counter()
        batches = read_batches(
            source,
            options,
            expected_header,
            column_count=len(columns),
            batch_rows=batch_rows,
            max_field_bytes=max_field_bytes,
        )
        for batch in batches:
            t_read = time.perf_counter()
            timings["read"] += int((t_read - started) * 1000)

            converted = convert_batch(batch.frame, columns, options, batch.extra_fields)
            t_convert = time.perf_counter()
            timings["transform"] += int((t_convert - t_read) * 1000)

            if converted.valid.height:
                writer.write_table(converted.valid.to_arrow().cast(valid_schema))
                for name, count in zip(
                    converted.valid.columns, converted.valid.null_count().row(0), strict=True
                ):
                    if name != "__df_row":
                        result.null_counts[name] += int(count)
            if converted.rejected.height:
                if rejected_writer is None:
                    rejected_writer = pq.ParquetWriter(
                        rejected_path, reject_schema, compression="zstd"
                    )
                rejected_writer.write_table(converted.rejected.to_arrow().cast(reject_schema))
                _collect_samples(result, converted.rejected)

            result.rows_total += batch.frame.height
            result.rows_valid += converted.valid.height
            result.rows_rejected += converted.rejected.height
            result.reasons.update(converted.reasons)
            result.column_failures.update(converted.column_failures)
            started = time.perf_counter()
            timings["write"] += int((started - t_convert) * 1000)

            on_progress(
                Progress(
                    rows_processed=result.rows_total,
                    bytes_processed=min(batch.bytes_read, bytes_total),
                    bytes_total=bytes_total,
                )
            )
    finally:
        writer.close()
        if rejected_writer is not None:
            rejected_writer.close()

    result.data_path = data_path
    result.rejected_path = rejected_path if rejected_writer is not None else None
    result.timings_ms = dict(timings)
    return result


def _collect_samples(result: PipelineResult, rejected: Any) -> None:
    room = MAX_SAMPLES - len(result.samples)
    if room <= 0:
        return
    # Amostras sem valores: o conteúdo fica apenas no Parquet de rejeitados, sob autorização.
    for row in rejected.select(META_COLUMNS).head(room).iter_rows(named=True):
        result.samples.append(
            {
                "row": row["__df_row"],
                "line": row["__df_line"],
                "reason": row["__df_reason"],
                "column": row["__df_column"],
                "detail": row["__df_detail"],
            }
        )
