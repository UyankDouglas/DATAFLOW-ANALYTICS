"""Configuração da aplicação, lida exclusivamente de variáveis de ambiente."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

MB = 1024 * 1024


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    environment: Literal["development", "test", "production"] = "development"
    app_name: str = "DataFlow Analytics"
    # URL pública do frontend, usada em links de e-mail (ex.: redefinição de senha).
    app_base_url: str = "http://localhost:8080"

    secret_key: SecretStr = SecretStr("dev-insecure-secret-change-me")
    database_url: str = "postgresql+psycopg://dataflow:dataflow@localhost:5432/dataflow"
    redis_url: str = "redis://localhost:6379/0"

    # Armazenamento de objetos compatível com S3 (MinIO em desenvolvimento).
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_access_key: SecretStr = SecretStr("dataflow")
    s3_secret_key: SecretStr = SecretStr("dataflow-secret")
    s3_bucket: str = "dataflow"

    # Sessão e cookies
    session_cookie_name: str = "df_session"
    csrf_cookie_name: str = "df_csrf"
    csrf_header_name: str = "X-CSRF-Token"
    session_ttl_hours: int = 12
    cookie_secure: bool = False
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:8080", "http://localhost:5173"]
    )

    # Limites de upload e processamento (ajustáveis por ambiente)
    max_csv_mb: int = 100
    max_xlsx_mb: int = 25
    upload_chunk_bytes: int = 1 * MB
    preview_sample_bytes: int = 2 * MB
    preview_rows: int = 20
    inference_rows: int = 1000
    max_columns: int = 500
    max_field_bytes: int = 1 * MB
    processing_batch_rows: int = 50_000
    max_rejection_samples: int = 200
    rows_page_size_max: int = 200

    # Celery / jobs
    job_max_attempts: int = 3
    job_stale_after_seconds: int = 300
    job_requeue_after_seconds: int = 600

    # Rate limiting (requisições por janela)
    rate_limit_enabled: bool = True
    login_limit_per_5min: int = 10
    register_limit_per_hour: int = 10
    forgot_limit_per_hour: int = 5
    upload_limit_per_min: int = 30

    # E-mail (Mailpit em desenvolvimento; qualquer SMTP em produção)
    smtp_host: str | None = "localhost"
    smtp_port: int = 1025
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_use_tls: bool = False
    smtp_from: str = "DataFlow Analytics <no-reply@dataflow.local>"
    password_reset_ttl_minutes: int = 30

    # Diretórios locais de trabalho (temporários e cache de Parquet imutável)
    work_dir: Path = Path("/tmp/dataflow")  # noqa: S108 - diretório dedicado, recriado no start
    cache_max_mb: int = 2048

    log_level: str = "INFO"

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("s3_endpoint_url", "smtp_host", "smtp_user", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def max_csv_bytes(self) -> int:
        return self.max_csv_mb * MB

    @property
    def max_xlsx_bytes(self) -> int:
        return self.max_xlsx_mb * MB

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def temp_dir(self) -> Path:
        return self.work_dir / "tmp"

    @property
    def cache_dir(self) -> Path:
        return self.work_dir / "cache"

    def validate_for_production(self) -> None:
        """Impede subir em produção com segredos de desenvolvimento."""
        if not self.is_production:
            return
        problems: list[str] = []
        if (
            self.secret_key.get_secret_value().startswith("dev-")
            or len(self.secret_key.get_secret_value()) < 32
        ):
            problems.append("SECRET_KEY precisa ter ao menos 32 caracteres e não ser o padrão")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE deve ser true em produção")
        if self.s3_secret_key.get_secret_value() == "dataflow-secret":
            problems.append("S3_SECRET_KEY não pode ser o valor padrão")
        if problems:
            raise RuntimeError("Configuração insegura: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
