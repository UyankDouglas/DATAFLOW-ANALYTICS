"""A API não pode subir em produção com configuração insegura."""

import pytest

from app.core.config import Settings


def _production(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "production",
        "secret_key": "s" * 48,
        "cookie_secure": True,
        "s3_secret_key": "senha-forte-do-armazenamento",
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_secure_production_config_is_accepted() -> None:
    _production().validate_for_production()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"secret_key": "dev-insecure-secret-change-me"}, "SECRET_KEY"),
        ({"secret_key": "curta"}, "SECRET_KEY"),
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"s3_secret_key": "dataflow-secret"}, "S3_SECRET_KEY"),
    ],
)
def test_insecure_production_config_is_refused(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(RuntimeError, match=message):
        _production(**overrides).validate_for_production()


def test_development_does_not_require_production_secrets() -> None:
    Settings(
        _env_file=None, environment="development", cookie_secure=False
    ).validate_for_production()  # type: ignore[call-arg]
