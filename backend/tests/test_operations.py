"""Operação: publicação de tarefas, e-mails, logs sem dados sensíveis, saúde e documentação."""

import json
import logging
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient
from kombu.exceptions import OperationalError
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.config import Settings, get_settings
from app.core.logging import JsonFormatter
from app.services import email as email_service
from app.services import storage
from app.tasks import dispatch
from app.tasks import email as email_tasks
from tests.conftest import REAL_SEND

TOKEN = "token-secreto-de-teste-0123456789"


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Mensagens entregues ao Celery pela publicação real (sem broker)."""
    from app.tasks.celery_app import celery_app

    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(dispatch, "_send", REAL_SEND)
    monkeypatch.setattr(
        celery_app, "send_task", lambda name, **options: sent.append({"name": name, **options})
    )
    return sent


def test_email_tasks_never_expose_address_or_token_in_task_logs(
    published: list[dict[str, Any]],
) -> None:
    assert dispatch.enqueue_password_reset_email("pessoa@example.com", TOKEN)
    assert dispatch.enqueue_invitation_email("pessoa@example.com", TOKEN, "Empresa", "analyst")
    assert dispatch.enqueue_export(__import__("uuid").uuid4())
    reset, invitation, export = published
    assert reset["args"] == ["pessoa@example.com", TOKEN]  # o worker recebe os dados reais
    for message in (reset, invitation):
        assert message["argsrepr"] == dispatch.REDACTED_ARGS
    assert export["argsrepr"] is None  # ids não são sensíveis: o Celery mostra os argumentos


def test_publish_failure_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks.celery_app import celery_app

    def broken(*_: Any, **__: Any) -> None:
        raise OperationalError("broker fora do ar")

    monkeypatch.setattr(dispatch, "_send", REAL_SEND)
    monkeypatch.setattr(celery_app, "send_task", broken)
    assert dispatch.enqueue_job(__import__("uuid").uuid4()) is False


def test_log_formatter_scrubs_task_arguments() -> None:
    record = logging.LogRecord("celery.app.trace", logging.ERROR, "", 0, "falhou", (), None)
    record.data = {"name": "email.password_reset", "args": ["pessoa@example.com", TOKEN]}
    line = json.loads(JsonFormatter().format(record))
    assert line["data"] == {"name": "email.password_reset", "args": "<omitido>"}
    assert TOKEN not in json.dumps(line)


def test_email_tasks_build_links_with_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(email_tasks, "send_email", lambda *args: sent.append(args))
    email_tasks.send_password_reset("pessoa@example.com", "a b")
    email_tasks.send_invitation("pessoa@example.com", TOKEN, "Empresa", "viewer")
    (to, subject, body), (_, invite_subject, invite_body) = sent
    assert to == "pessoa@example.com"
    assert "/redefinir-senha?token=a%20b" in body
    assert "Redefinição de senha" in subject
    assert f"/convite?token={TOKEN}" in invite_body
    assert "Visualizador" in invite_body
    assert "Empresa" in invite_subject


class FakeSMTP:
    instances: ClassVar[list["FakeSMTP"]] = []

    def __init__(self, host: str, port: int, timeout: int) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.calls: list[str] = []
        self.messages: list[Any] = []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *_: object) -> None:
        self.calls.append("quit")

    def starttls(self) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login:{user}:{len(password)}")

    def send_message(self, message: Any) -> None:
        self.messages.append(message)


def test_send_email_uses_tls_and_credentials_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSMTP.instances.clear()
    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)
    settings = get_settings().model_copy(
        update={
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_use_tls": True,
            "smtp_user": "envio",
            "smtp_password": __import__("pydantic").SecretStr("senha-smtp"),
        }
    )
    monkeypatch.setattr(email_service, "get_settings", lambda: settings)
    email_service.send_email("pessoa@example.com", "Assunto", "Corpo")
    (client,) = FakeSMTP.instances
    assert (client.host, client.port) == ("smtp.example.com", 587)
    assert client.calls == ["starttls", "login:envio:10", "quit"]
    assert client.messages[0]["To"] == "pessoa@example.com"
    assert client.messages[0].get_content().strip() == "Corpo"


def test_send_email_without_smtp_is_a_logged_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSMTP.instances.clear()
    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)
    email_service.send_email("pessoa@example.com", "Assunto", "Corpo")  # SMTP_HOST vazio nos testes
    assert FakeSMTP.instances == []


def test_readiness_reports_each_dependency(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, fake_redis: Any
) -> None:
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json()["checks"] == {
        "database": True,
        "redis": True,
        "storage": True,
    }

    def down() -> bool:
        raise RedisConnectionError("fora do ar")

    monkeypatch.setattr(fake_redis, "ping", down)
    monkeypatch.setattr(storage, "is_available", lambda: False)
    degraded = client.get("/health/ready")
    assert degraded.status_code == 503
    assert degraded.json() == {
        "status": "degraded",
        "checks": {"database": True, "redis": False, "storage": False},
    }


@pytest.mark.parametrize(
    ("environment", "expose", "expected"),
    [
        ("development", None, True),
        ("production", None, False),
        ("production", True, True),
        ("development", False, False),
    ],
)
def test_api_docs_are_off_in_production_unless_requested(
    environment: str, expose: bool | None, expected: bool
) -> None:
    settings = Settings(_env_file=None, environment=environment, expose_api_docs=expose)  # type: ignore[call-arg]
    assert settings.api_docs is expected


def test_app_without_docs_serves_no_openapi(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main

    settings = get_settings().model_copy(update={"expose_api_docs": False})
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    with TestClient(main.create_app()) as docs_off:
        assert docs_off.get("/api/docs").status_code == 404
        assert docs_off.get("/api/openapi.json").status_code == 404


def test_duckdb_queries_share_a_bounded_number_of_slots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    import threading

    from app.analytics import query
    from app.core.errors import ServiceUnavailable

    monkeypatch.setattr(query, "_slots", threading.BoundedSemaphore(1))
    monkeypatch.setattr(query, "QUERY_TIMEOUT_SECONDS", 0.05)
    with query.query_connection(tmp_path) as con:
        assert con.execute("SELECT 1").fetchone() == (1,)
        with pytest.raises(ServiceUnavailable) as busy, query.query_connection(tmp_path):
            pass
        assert busy.value.code == "query_busy"
        assert busy.value.status_code == 503
    with query.query_connection(tmp_path) as con:  # a vaga volta ao terminar a consulta
        assert con.execute("SELECT current_setting('memory_limit')").fetchone() is not None
