"""Tipos, formatos e opções de leitura aceitos pelo pipeline (allowlists)."""

import unicodedata
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Versão das regras do pipeline. Muda sempre que a semântica de conversão mudar,
# para que cada versão de dataset registre com quais regras foi produzida.
RULES_VERSION = "1.0.0"

RESERVED_PREFIX = "__df_"


class DataType(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    DATE = "date"
    DATETIME = "datetime"
    BOOLEAN = "boolean"


Encoding = Literal["utf-8", "windows-1252", "iso-8859-1"]
Delimiter = Literal[",", ";", "\t", "|"]

ENCODING_LABELS: dict[str, str] = {
    "utf-8": "UTF-8",
    "windows-1252": "Windows-1252 (ANSI)",
    "iso-8859-1": "ISO-8859-1 (Latin-1)",
}

DATE_FORMATS: dict[str, str] = {
    "%d/%m/%Y": "dd/mm/aaaa",
    "%Y-%m-%d": "aaaa-mm-dd",
    "%d-%m-%Y": "dd-mm-aaaa",
    "%d.%m.%Y": "dd.mm.aaaa",
    "%m/%d/%Y": "mm/dd/aaaa",
    "%Y/%m/%d": "aaaa/mm/dd",
}

DATETIME_FORMATS: dict[str, str] = {
    "%d/%m/%Y %H:%M:%S": "dd/mm/aaaa hh:mm:ss",
    "%d/%m/%Y %H:%M": "dd/mm/aaaa hh:mm",
    "%Y-%m-%d %H:%M:%S": "aaaa-mm-dd hh:mm:ss",
    "%Y-%m-%dT%H:%M:%S": "aaaa-mm-ddThh:mm:ss",
    "%Y-%m-%d %H:%M": "aaaa-mm-dd hh:mm",
    "%m/%d/%Y %H:%M:%S": "mm/dd/aaaa hh:mm:ss",
}

BOOLEAN_TRUE = frozenset({"true", "verdadeiro", "sim", "s", "yes", "y", "1"})
BOOLEAN_FALSE = frozenset({"false", "falso", "nao", "não", "n", "no", "0"})

MAX_DECIMAL_SCALE = 18
DECIMAL_PRECISION = 38

DEFAULT_NULL_VALUES = ["", "NULL", "null"]


class ParseOptions(BaseModel):
    encoding: Encoding = "utf-8"
    delimiter: Delimiter = ","
    has_header: bool = True
    decimal_separator: Literal[".", ","] = "."
    thousands_separator: Literal["", ".", ",", " "] = ""
    null_values: list[str] = Field(default_factory=lambda: list(DEFAULT_NULL_VALUES), max_length=20)

    @field_validator("null_values")
    @classmethod
    def _check_nulls(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            if len(value) > 30:
                raise ValueError("cada representação de nulo pode ter no máximo 30 caracteres")
            if value not in cleaned:
                cleaned.append(value)
        return cleaned

    @model_validator(mode="after")
    def _check_separators(self) -> "ParseOptions":
        if self.thousands_separator and self.thousands_separator == self.decimal_separator:
            raise ValueError("separador de milhar não pode ser igual ao separador decimal")
        if self.thousands_separator and self.thousands_separator == self.delimiter:
            raise ValueError("separador de milhar não pode ser igual ao delimitador")
        if self.decimal_separator == self.delimiter:
            raise ValueError("separador decimal não pode ser igual ao delimitador")
        return self


def normalize_column_name(name: str) -> str:
    return unicodedata.normalize("NFC", name).strip()


class ColumnConfig(BaseModel):
    position: int = Field(ge=0)
    source_name: str = Field(max_length=255)
    name: str = Field(min_length=1, max_length=63)
    data_type: DataType
    format: str | None = None
    scale: int | None = Field(default=None, ge=0, le=MAX_DECIMAL_SCALE)

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        value = normalize_column_name(value)
        if not value:
            raise ValueError("o nome da coluna não pode ser vazio")
        if value.lower().startswith(RESERVED_PREFIX):
            raise ValueError(f"nomes iniciados por '{RESERVED_PREFIX}' são reservados")
        if any(ord(ch) < 32 or ch == '"' for ch in value):
            raise ValueError("o nome contém caracteres não permitidos")
        return value

    @model_validator(mode="after")
    def _check_format(self) -> "ColumnConfig":
        if self.data_type == DataType.DATE:
            if self.format not in DATE_FORMATS:
                raise ValueError(f"coluna '{self.name}': formato de data inválido ou ausente")
        elif self.data_type == DataType.DATETIME:
            if self.format not in DATETIME_FORMATS:
                raise ValueError(
                    f"coluna '{self.name}': formato de data e hora inválido ou ausente"
                )
        else:
            self.format = None
        if self.data_type == DataType.DECIMAL:
            if self.scale is None:
                raise ValueError(f"coluna '{self.name}': informe a quantidade de casas decimais")
        else:
            self.scale = None
        return self
