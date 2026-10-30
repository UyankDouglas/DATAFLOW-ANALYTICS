from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from app.processing.inference import infer_column
from app.processing.inspection import FileRejected, StreamInspector, parse_sample, sniff_delimiter
from app.processing.pipeline import Progress, run_csv_pipeline
from app.processing.reader import EncodingMismatch, HeaderMismatch
from app.processing.types import ColumnConfig, DataType, ParseOptions

BR = ParseOptions(delimiter=";", decimal_separator=",", thousands_separator=".")


def inspect(data: bytes) -> dict:
    inspector = StreamInspector()
    for i in range(0, len(data), 7):  # blocos pequenos exercitam fronteiras multibyte
        inspector.feed(data[i : i + 7])
    return inspector.finish()


def test_inspector_detects_utf8_delimiter_and_br_numbers() -> None:
    result = inspect("produto;valor\nCafé;1.234,50\nPão;2,00\n".encode())
    assert result["utf8_valid"] is True
    assert result["delimiter"] == ";"
    assert (result["decimal_separator"], result["thousands_separator"]) == (",", ".")
    assert result["line_count"] == 3


def test_inspector_flags_non_utf8_without_guessing_silently() -> None:
    result = inspect("nome,cidade\nJoão,São Paulo\n".encode("cp1252"))
    assert result["utf8_valid"] is False
    assert result["encoding"] is None
    assert result["suggested_encoding"] == "windows-1252"


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"PK\x03\x04rest-of-zip", "content_mismatch"),
        (b"\x89PNG\r\n\x1a\n....", "content_mismatch"),
        ("a,b\n1,2\n".encode("utf-16"), "unsupported_encoding"),
        (b"a,b\x00\n1,2\n", "content_mismatch"),
    ],
)
def test_inspector_rejects_binary_content(payload: bytes, code: str) -> None:
    with pytest.raises(FileRejected) as error:
        inspect(payload)
    assert error.value.code == code


def test_inspector_rejects_empty_file() -> None:
    with pytest.raises(FileRejected):
        StreamInspector().finish()


def test_sniff_delimiter_prefers_consistent_field_counts() -> None:
    assert sniff_delimiter("a,b,c\n1,2,3\n4,5,6\n") == ","
    assert sniff_delimiter("a;b;c\n1,5;2;3\n4;5,1;6\n") == ";"
    assert sniff_delimiter("a\tb\n1\t2\n") == "\t"


def test_inference_types_and_leading_zeros() -> None:
    opts = BR
    assert infer_column(0, "q", ["1", "20", "-3"], opts).inferred_type == DataType.INTEGER
    decimal = infer_column(0, "v", ["1.234,56", "10", "0,5"], opts)
    assert decimal.inferred_type == DataType.DECIMAL
    assert decimal.scale == 2
    assert infer_column(0, "cep", ["01310100", "20040002"], opts).inferred_type == DataType.TEXT
    assert infer_column(0, "ok", ["Sim", "não", "S"], opts).inferred_type == DataType.BOOLEAN
    empty = infer_column(0, "x", ["", "NULL", ""], opts)
    assert empty.is_empty
    assert "coluna_vazia_na_amostra" in empty.warnings


def test_inference_flags_ambiguous_dates() -> None:
    ambiguous = infer_column(0, "d", ["01/02/2024", "03/04/2024"], BR)
    assert ambiguous.inferred_type == DataType.DATE
    assert ambiguous.format == "%d/%m/%Y"
    assert "%m/%d/%Y" in ambiguous.ambiguous_formats
    clear = infer_column(0, "d", ["13/02/2024", "31/12/2024"], BR)
    assert clear.ambiguous_formats == []


def test_parse_sample_handles_header_quotes_and_ragged_rows() -> None:
    data = b'id;nome\n1;"Ana; Maria"\n2\n\n3;Bia\n'
    sample = parse_sample(data, ParseOptions(delimiter=";"), truncated=False, max_rows=100)
    assert sample.header == ["id", "nome"]
    assert sample.rows[0] == ["1", "Ana; Maria"]
    assert sample.ragged_rows == 1
    assert sample.empty_rows == 1
    assert sample.complete


def _columns() -> list[ColumnConfig]:
    return [
        ColumnConfig(
            position=0, source_name="data", name="data", data_type=DataType.DATE, format="%d/%m/%Y"
        ),
        ColumnConfig(position=1, source_name="nome", name="nome", data_type=DataType.TEXT),
        ColumnConfig(
            position=2, source_name="valor", name="valor", data_type=DataType.DECIMAL, scale=2
        ),
        ColumnConfig(position=3, source_name="qtd", name="qtd", data_type=DataType.INTEGER),
        ColumnConfig(position=4, source_name="ativo", name="ativo", data_type=DataType.BOOLEAN),
    ]


def _run(tmp_path: Path, content: bytes, options: ParseOptions = BR, batch_rows: int = 2) -> tuple:
    source = tmp_path / "in.csv"
    source.write_bytes(content)
    progress: list[Progress] = []
    result = run_csv_pipeline(
        source,
        tmp_path / "out",
        options,
        _columns(),
        ["data", "nome", "valor", "qtd", "ativo"],
        batch_rows=batch_rows,
        max_field_bytes=1024,
        on_progress=progress.append,
    )
    return result, progress


def test_pipeline_converts_types_and_preserves_decimal_precision(tmp_path: Path) -> None:
    content = "data;nome;valor;qtd;ativo\n31/12/2024;  Ana  ;1.234,56;3;sim\n01/01/2025;Bia;0,10; 7 ;NÃO\n".encode()
    result, _ = _run(tmp_path, content)
    rows = pq.read_table(result.data_path).to_pylist()
    assert rows[0]["valor"] == Decimal("1234.56")
    assert rows[1]["valor"] == Decimal("0.10")
    assert rows[0]["nome"] == "  Ana  "  # texto preservado exatamente
    assert rows[1]["qtd"] == 7
    assert rows[1]["ativo"] is False
    schema = pq.read_schema(result.data_path)
    assert str(schema.field("valor").type) == "decimal128(38, 2)"


def test_pipeline_rejects_with_traceable_reasons_and_reconciles(tmp_path: Path) -> None:
    content = (
        b"data;nome;valor;qtd;ativo\n"
        b"31/12/2024;Ana;10,00;1;s\n"  # válido
        b"32/12/2024;Bia;10,00;1;s\n"  # data inválida
        b"01/01/2025;Cid;1,999;1;s\n"  # escala excedida (não arredonda)
        b"\n"  # linha vazia
        b"01/01/2025;Di\n"  # campos a menos
        b"01/01/2025;Eve;1,00;1;s;extra\n"  # campos a mais
        b"01/01/2025;Fe;NULL;;\n"  # nulos são válidos
    )
    result, progress = _run(tmp_path, content)
    assert result.reconciliation == {
        "received": 7,
        "valid": 2,
        "rejected": 5,
        "duplicates": None,
        "duplicates_policy": "nao_aplicada",
        "consistent": True,
    }
    assert dict(result.reasons) == {
        "tipo_invalido": 1,
        "casas_decimais_excedidas": 1,
        "linha_vazia": 1,
        "campos_a_menos": 1,
        "campos_a_mais": 1,
    }
    assert dict(result.column_failures) == {"data": 1, "valor": 1}
    rejected = pq.read_table(result.rejected_path).to_pylist()
    bad_date = next(r for r in rejected if r["__df_reason"] == "tipo_invalido")
    assert bad_date["__df_column"] == "data"
    assert bad_date["data"] == "32/12/2024"  # valor original preservado
    assert bad_date["__df_line"] == 3
    assert progress[-1].rows_processed == 7
    assert len(progress) == 4  # lotes de 2 registros: progresso por lote concluído
    valid = pq.read_table(result.data_path).to_pylist()
    assert valid[1]["valor"] is None
    assert valid[1]["qtd"] is None


def test_pipeline_fails_explicitly_on_wrong_encoding(tmp_path: Path) -> None:
    content = "data;nome;valor;qtd;ativo\n01/01/2025;João;1,00;1;s\n".encode("cp1252")
    with pytest.raises(EncodingMismatch):
        _run(tmp_path, content)
    result, _ = _run(tmp_path, content, BR.model_copy(update={"encoding": "windows-1252"}))
    assert pq.read_table(result.data_path).to_pylist()[0]["nome"] == "João"


def test_pipeline_rejects_header_divergence(tmp_path: Path) -> None:
    with pytest.raises(HeaderMismatch):
        _run(tmp_path, b"outra;coisa;aqui;x;y\n1;2;3;4;5\n")


def test_pipeline_rejects_oversized_or_malformed_fields(tmp_path: Path) -> None:
    big = "x" * 2000
    content = (
        f'data;nome;valor;qtd;ativo\n01/01/2025;"{big}";1,00;1;s\n01/01/2025;ok;1,00;1;s\n'.encode()
    )
    result, _ = _run(tmp_path, content)
    assert result.reasons["csv_malformado"] == 1
    assert result.rows_valid == 1


def test_column_config_rejects_reserved_and_unsafe_names() -> None:
    with pytest.raises(ValueError, match="reservados"):
        ColumnConfig(position=0, source_name="a", name="__df_row", data_type=DataType.TEXT)
    with pytest.raises(ValueError, match="não permitidos"):
        ColumnConfig(position=0, source_name="a", name='a"; DROP', data_type=DataType.TEXT)
    with pytest.raises(ValueError, match="formato"):
        ColumnConfig(position=0, source_name="a", name="d", data_type=DataType.DATE, format="%Q")
