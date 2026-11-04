"""Pipelines de importação (CSV/XLSX → Parquet) e de transformação (versão → nova versão).

Sem dependência de banco ou armazenamento: o orquestrador (services/job_runner.py) cuida de
estado, cancelamento e publicação; aqui só se transformam arquivos locais, reportando
progresso real a cada lote.

Arquivos gerados por execução:
- data.parquet: registros publicados (tipados);
- rejected.parquet: todo registro que não entrou na versão — rejeitado, filtrado ou duplicado —
  com motivo, regra, coluna, detalhe e os valores de entrada em texto.
"""

import hashlib
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq

from app.processing.convert import (
    CATEGORY_FILTERED,
    CATEGORY_REJECTED,
    META_COLUMNS,
    META_SCHEMA,
    convert_batch,
)
from app.processing.reader import RawBatch, read_batches
from app.processing.transforms import (
    DUPLICATE_REASON,
    RulePlan,
    apply_rules,
    duplicate_exclusions,
    mark_duplicates,
)
from app.processing.types import DECIMAL_PRECISION, ColumnConfig, ColumnSpec, DataType, ParseOptions
from app.processing.xlsx import XlsxReadStats, read_xlsx_batches

MAX_SAMPLES = 200


@dataclass
class Progress:
    rows_processed: int
    bytes_processed: int | None = None
    bytes_total: int | None = None


@dataclass
class PipelineResult:
    rows_total: int = 0
    rows_valid: int = 0
    rows_rejected: int = 0
    rows_filtered: int = 0
    rows_duplicates: int | None = None  # None = deduplicação não aplicada
    reasons: Counter[str] = field(default_factory=Counter)
    column_failures: Counter[str] = field(default_factory=Counter)
    null_counts: Counter[str] = field(default_factory=Counter)
    samples: list[dict[str, Any]] = field(default_factory=list)
    output_schema: list[ColumnSpec] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data_path: Path | None = None
    rejected_path: Path | None = None
    timings_ms: dict[str, int] = field(default_factory=dict)

    @property
    def reconciliation(self) -> dict[str, Any]:
        duplicates = self.rows_duplicates
        accounted = self.rows_valid + self.rows_rejected + self.rows_filtered + (duplicates or 0)
        return {
            "received": self.rows_total,
            "valid": self.rows_valid,
            "rejected": self.rows_rejected,
            "filtered": self.rows_filtered,
            "duplicates": duplicates,
            # Duplicados removidos nunca contam como válidos: cada registro está em uma só categoria.
            "duplicates_policy": "nao_aplicada" if duplicates is None else "removidos_dos_validos",
            "consistent": self.rows_total == accounted,
        }


def arrow_type(data_type: DataType, scale: int | None) -> pa.DataType:
    match data_type:
        case DataType.TEXT:
            return pa.string()
        case DataType.INTEGER:
            return pa.int64()
        case DataType.DECIMAL:
            return pa.decimal128(DECIMAL_PRECISION, scale or 0)
        case DataType.DATE:
            return pa.date32()
        case DataType.DATETIME:
            return pa.timestamp("us")
        case DataType.BOOLEAN:
            return pa.bool_()


def data_schema(columns: list[ColumnSpec]) -> pa.Schema:
    fields = [pa.field("__df_row", pa.int64(), nullable=False)]
    fields += [pa.field(c.name, arrow_type(c.data_type, c.scale)) for c in columns]
    return pa.schema(fields)


_META_ARROW = {
    "__df_row": pa.int64(),
    "__df_line": pa.int64(),
    "__df_reason": pa.string(),
    "__df_column": pa.string(),
    "__df_detail": pa.string(),
    "__df_category": pa.string(),
    "__df_rule": pa.int32(),
    "__df_duplicate_of": pa.int64(),
}


def rejected_schema(input_names: list[str]) -> pa.Schema:
    fields = [pa.field(name, _META_ARROW[name]) for name in META_COLUMNS]
    fields += [pa.field(name, pa.string()) for name in input_names]
    return pa.schema(fields)


def specs_from_columns(columns: list[ColumnConfig]) -> list[ColumnSpec]:
    return [
        ColumnSpec(name=c.name, data_type=c.data_type, format=c.format, scale=c.scale)
        for c in columns
    ]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _Outputs:
    """Escritores Parquet abertos sob demanda (o de rejeitados só se houver exclusões)."""

    def __init__(
        self, out_dir: Path, valid: pa.Schema, rejected: pa.Schema, data_name: str = "data.parquet"
    ) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        self.data_path = out_dir / data_name
        self.rejected_path = out_dir / "rejected.parquet"
        self.valid_schema = valid
        self.rejected_schema = rejected
        self.writer = pq.ParquetWriter(self.data_path, valid, compression="zstd")
        self.rejected_writer: pq.ParquetWriter | None = None

    def write_valid(self, frame: pl.DataFrame) -> None:
        if frame.height:
            self.writer.write_table(frame.to_arrow().cast(self.valid_schema))

    def write_rejected(self, frame: pl.DataFrame) -> None:
        if not frame.height:
            return
        if self.rejected_writer is None:
            self.rejected_writer = pq.ParquetWriter(
                self.rejected_path, self.rejected_schema, compression="zstd"
            )
        table = frame.select(self.rejected_schema.names).to_arrow().cast(self.rejected_schema)
        self.rejected_writer.write_table(table)

    def close(self) -> None:
        self.writer.close()
        if self.rejected_writer is not None:
            self.rejected_writer.close()

    @property
    def has_rejected(self) -> bool:
        return self.rejected_writer is not None


def _collect_samples(result: PipelineResult, rejected: pl.DataFrame) -> None:
    room = MAX_SAMPLES - len(result.samples)
    if room <= 0 or not rejected.height:
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
                "category": row["__df_category"],
                "rule": row["__df_rule"],
                "duplicate_of": row["__df_duplicate_of"],
            }
        )


def _null_counts(path: Path) -> dict[str, int]:
    counts = pl.scan_parquet(path).drop("__df_row").null_count().collect()
    return {name: int(counts[name][0]) for name in counts.columns}


def run_import_pipeline(
    batches: Iterable[RawBatch],
    out_dir: Path,
    options: ParseOptions,
    columns: list[ColumnConfig],
    *,
    bytes_total: int | None,
    on_progress: Callable[[Progress], None],
) -> PipelineResult:
    result = PipelineResult(output_schema=specs_from_columns(columns))
    outputs = _Outputs(
        out_dir, data_schema(result.output_schema), rejected_schema([c.name for c in columns])
    )
    timings = Counter[str]()
    try:
        started = time.perf_counter()
        for batch in batches:
            t_read = time.perf_counter()
            timings["read"] += int((t_read - started) * 1000)

            converted = convert_batch(batch.frame, columns, options, batch.extra_fields)
            t_convert = time.perf_counter()
            timings["transform"] += int((t_convert - t_read) * 1000)

            outputs.write_valid(converted.valid)
            outputs.write_rejected(converted.rejected)
            _collect_samples(result, converted.rejected)

            result.rows_total += batch.frame.height
            result.rows_valid += converted.valid.height
            result.rows_rejected += converted.rejected.height
            result.reasons.update(converted.reasons)
            result.column_failures.update(converted.column_failures)
            started = time.perf_counter()
            timings["write"] += int((started - t_convert) * 1000)

            bytes_processed = (
                min(batch.bytes_read, bytes_total)
                if batch.bytes_read is not None and bytes_total is not None
                else None
            )
            on_progress(
                Progress(
                    rows_processed=result.rows_total,
                    bytes_processed=bytes_processed,
                    bytes_total=bytes_total,
                )
            )
    finally:
        outputs.close()

    result.data_path = outputs.data_path
    result.rejected_path = outputs.rejected_path if outputs.has_rejected else None
    result.null_counts.update(_null_counts(outputs.data_path))
    result.timings_ms = dict(timings)
    return result


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
    batches = read_batches(
        source,
        options,
        expected_header,
        column_count=len(columns),
        batch_rows=batch_rows,
        max_field_bytes=max_field_bytes,
    )
    return run_import_pipeline(
        batches,
        out_dir,
        options,
        columns,
        bytes_total=source.stat().st_size,
        on_progress=on_progress,
    )


def run_xlsx_pipeline(
    source: Path,
    out_dir: Path,
    options: ParseOptions,
    columns: list[ColumnConfig],
    expected_header: list[str] | None,
    *,
    first_column: int,
    batch_rows: int,
    on_progress: Callable[[Progress], None],
) -> PipelineResult:
    stats = XlsxReadStats()
    batches = read_xlsx_batches(
        source,
        options,
        expected_header,
        column_count=len(columns),
        first_column=first_column,
        batch_rows=batch_rows,
        stats=stats,
    )
    result = run_import_pipeline(
        batches, out_dir, options, columns, bytes_total=None, on_progress=on_progress
    )
    if stats.trailing_empty_rows:
        result.warnings.append(
            f"{stats.trailing_empty_rows} linha(s) vazia(s) ao final da aba foram ignoradas: "
            "não são registros."
        )
    return result


def _input_as_text(frame: pl.DataFrame, schema: list[ColumnSpec]) -> pl.DataFrame:
    """Valores de entrada em texto, para registrar o "valor original" das exclusões."""
    exprs: list[pl.Expr] = [pl.col("__df_row")]
    for spec in schema:
        column = pl.col(spec.name)
        match spec.data_type:
            case DataType.TEXT:
                exprs.append(column)
            case DataType.DATETIME:
                exprs.append(column.dt.strftime("%Y-%m-%d %H:%M:%S").alias(spec.name))
            case DataType.DATE:
                exprs.append(column.dt.strftime("%Y-%m-%d").alias(spec.name))
            case DataType.BOOLEAN:
                exprs.append(
                    pl.when(column)
                    .then(pl.lit("true"))
                    .when(~column)
                    .then(pl.lit("false"))
                    .alias(spec.name)
                )
            case _:
                exprs.append(column.cast(pl.String).alias(spec.name))
    return frame.select(exprs)


def _with_input_values(
    excluded: pl.DataFrame, source: pl.DataFrame, schema: list[ColumnSpec]
) -> pl.DataFrame:
    meta = excluded.with_columns(
        pl.lit(None, dtype=pl.Int64).alias("__df_line"),
        *(
            [pl.lit(None, dtype=pl.Int64).alias("__df_duplicate_of")]
            if "__df_duplicate_of" not in excluded.columns
            else []
        ),
    )
    joined = meta.join(_input_as_text(source, schema), on="__df_row", how="left")
    return joined.select([*META_COLUMNS, *[s.name for s in schema]]).cast(META_SCHEMA)  # type: ignore[arg-type]


def run_transform_pipeline(
    source: Path,
    out_dir: Path,
    input_schema: list[ColumnSpec],
    plan: RulePlan,
    *,
    batch_rows: int,
    rows_total: int,
    on_progress: Callable[[Progress], None],
) -> PipelineResult:
    """Aplica as regras a uma versão publicada (Parquet) e gera a nova versão.

    1ª passada, em lotes: regras de linha; exclusões gravadas com os valores de entrada.
    2ª passada, só se houver deduplicação: sobre o resultado inteiro da 1ª passada.
    """
    result = PipelineResult(output_schema=plan.output)
    input_names = [s.name for s in input_schema]
    dedup = plan.dedup is not None
    stage_name = "stage.parquet" if dedup else "data.parquet"
    outputs = _Outputs(
        out_dir, data_schema(plan.output), rejected_schema(input_names), data_name=stage_name
    )
    timings = Counter[str]()
    processed = 0
    try:
        parquet = pq.ParquetFile(source)
        started = time.perf_counter()
        for record_batch in parquet.iter_batches(
            batch_size=batch_rows, columns=["__df_row", *input_names]
        ):
            frame = pl.from_arrow(record_batch)
            assert isinstance(frame, pl.DataFrame)
            t_read = time.perf_counter()
            timings["read"] += int((t_read - started) * 1000)

            batch = apply_rules(frame, plan)
            t_apply = time.perf_counter()
            timings["transform"] += int((t_apply - t_read) * 1000)

            outputs.write_valid(batch.frame.select(["__df_row", *[s.name for s in plan.output]]))
            if batch.excluded.height:
                excluded = _with_input_values(batch.excluded, frame, input_schema)
                outputs.write_rejected(excluded)
                _collect_samples(result, excluded)
            result.reasons.update(batch.reasons)
            result.rows_rejected += batch.categories.get(CATEGORY_REJECTED, 0)
            result.rows_filtered += batch.categories.get(CATEGORY_FILTERED, 0)
            processed += frame.height
            result.rows_total = processed
            started = time.perf_counter()
            timings["write"] += int((started - t_apply) * 1000)
            on_progress(Progress(rows_processed=processed))

        if dedup:
            outputs.writer.close()  # o estágio é relido; o escritor de exclusões segue aberto
            t_dedup = time.perf_counter()
            data_path = out_dir / "data.parquet"
            removed = _deduplicate(
                outputs, data_path, plan, source, input_schema, result, batch_rows
            )
            result.rows_duplicates = removed
            result.reasons[DUPLICATE_REASON] += removed
            outputs.data_path.unlink(missing_ok=True)
            outputs.data_path = data_path
            timings["deduplicate"] = int((time.perf_counter() - t_dedup) * 1000)
    finally:
        outputs.close()

    result.rows_valid = pq.ParquetFile(outputs.data_path).metadata.num_rows
    result.data_path = outputs.data_path
    rejected_exists = outputs.rejected_path.exists()
    result.rejected_path = outputs.rejected_path if rejected_exists else None
    result.null_counts.update(_null_counts(outputs.data_path))
    result.timings_ms = dict(timings)
    if result.rows_total != rows_total:
        result.warnings.append(
            f"A versão de origem tinha {rows_total} registros, mas {result.rows_total} foram lidos."
        )
    return result


def _deduplicate(
    outputs: _Outputs,
    target: Path,
    plan: RulePlan,
    source: Path,
    input_schema: list[ColumnSpec],
    result: PipelineResult,
    batch_rows: int,
) -> int:
    """Mantém o primeiro/último registro de cada chave; os demais viram exclusões.

    Em memória ficam só as chaves, a marcação de cada registro e os pares (descartado, mantido).
    Mantidos e exclusões são gravados em lotes, na ordem dos registros (ADR-031).
    """
    stage = outputs.data_path
    keep, duplicates = mark_duplicates(pl.scan_parquet(stage), plan)

    offset = 0
    with pq.ParquetWriter(target, outputs.valid_schema, compression="zstd") as writer:
        for batch in pq.ParquetFile(stage).iter_batches(batch_size=batch_rows):
            kept = pa.Table.from_batches([batch]).filter(
                keep.slice(offset, batch.num_rows).to_arrow()
            )
            offset += batch.num_rows
            if kept.num_rows:
                writer.write_table(kept.cast(outputs.valid_schema))
    if offset != keep.len():
        raise RuntimeError("A marcação de duplicados não cobre o estágio inteiro.")
    if not duplicates.height:
        return 0

    names = [s.name for s in input_schema]
    duplicates = duplicates.sort("__df_row")
    duplicate_rows = duplicates.get_column("__df_row")
    written = 0
    for batch in pq.ParquetFile(source).iter_batches(
        batch_size=batch_rows, columns=["__df_row", *names]
    ):
        frame = pl.from_arrow(batch)
        assert isinstance(frame, pl.DataFrame)
        if not frame.height:
            continue
        # Só os duplicados dentro da faixa de números do lote podem estar nele.
        ids = frame.get_column("__df_row")
        first, last = ids.min(), ids.max()
        assert isinstance(first, int)
        assert isinstance(last, int)
        start = duplicate_rows.search_sorted(first, "left")
        end = duplicate_rows.search_sorted(last, "right")
        removed = duplicates.slice(start, end - start).join(
            frame.select("__df_row"), on="__df_row", how="semi"
        )
        if not removed.height:
            continue
        excluded = duplicate_exclusions(removed, plan)
        rows = _with_input_values(excluded, frame, input_schema).sort("__df_row")
        outputs.write_rejected(rows)
        _collect_samples(result, rows)
        written += rows.height
    if written != duplicates.height:
        raise RuntimeError("Há duplicados sem o registro correspondente na versão de origem.")
    return duplicates.height
