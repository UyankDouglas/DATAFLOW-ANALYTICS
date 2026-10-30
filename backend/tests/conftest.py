"""Fixtures de teste.

Por padrão os testes usam SQLite em arquivo temporário, S3 simulado (moto) e Redis simulado
(fakeredis), para rodar sem infraestrutura. Com TEST_DATABASE_URL apontando para PostgreSQL
(como na CI), o mesmo conjunto roda contra o banco real, com o esquema criado pelas migrations.
"""

import os
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

_TMP = Path(tempfile.mkdtemp(prefix="dataflow-tests-"))
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": os.environ.get(
            "TEST_DATABASE_URL", f"sqlite:///{(_TMP / 'test.db').as_posix()}"
        ),
        "WORK_DIR": str(_TMP / "work"),
        "S3_ENDPOINT_URL": "",
        "S3_BUCKET": "dataflow-test",
        "S3_ACCESS_KEY": "testing",
        "S3_SECRET_KEY": "testing",
        "SECRET_KEY": "test-secret-key-with-enough-length-0123456789",
        "SMTP_HOST": "",
        "LOG_LEVEL": "WARNING",
        "ALLOWED_ORIGINS": "http://testserver,http://localhost:8080",
        "PROCESSING_BATCH_ROWS": "1000",
    }
)

import fakeredis  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from moto import mock_aws  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core import redis as redis_module  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.db import get_engine, session_scope  # noqa: E402
from app.models import Base, Role, WorkspaceMember  # noqa: E402
from app.services import storage  # noqa: E402

IS_POSTGRES = get_settings().database_url.startswith("postgresql")
PASSWORD = "Senha-forte-123"


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    engine = get_engine()
    if IS_POSTGRES:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(cfg, "head")
    else:
        Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_db() -> Iterator[None]:
    yield
    engine = get_engine()
    tables = [t.name for t in reversed(Base.metadata.sorted_tables)]
    with engine.begin() as conn:
        if IS_POSTGRES:
            conn.execute(text("TRUNCATE " + ", ".join(tables) + " CASCADE"))
        else:
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            for table in tables:
                conn.execute(text(f"DELETE FROM {table}"))  # noqa: S608 - nomes vêm do metadata
            conn.execute(text("PRAGMA foreign_keys=ON"))


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> Iterator[fakeredis.FakeRedis]:
    server = fakeredis.FakeRedis(decode_responses=True)
    redis_module.get_redis.cache_clear()
    monkeypatch.setattr(redis_module.Redis, "from_url", classmethod(lambda cls, *a, **k: server))
    yield server
    redis_module.get_redis.cache_clear()


@pytest.fixture(autouse=True)
def s3() -> Iterator[Any]:
    with mock_aws():
        storage.get_s3.cache_clear()
        storage.ensure_bucket()
        yield storage.get_s3()
        storage.get_s3.cache_clear()


@pytest.fixture(autouse=True)
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, list[Any]]]:
    """Captura tarefas publicadas em vez de enviá-las ao broker."""
    calls: list[tuple[str, list[Any]]] = []

    def fake_send(name: str, args: list[Any], task_id: str | None = None) -> bool:
        calls.append((name, args))
        return True

    monkeypatch.setattr("app.tasks.dispatch._send", fake_send)
    return calls


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app, base_url="http://testserver") as test_client:
        yield test_client


def csrf(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(get_settings().csrf_cookie_name)
    if not token:
        token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    return {"X-CSRF-Token": token}


def register(
    client: TestClient, email: str | None = None, workspace: str = "Empresa Teste"
) -> dict[str, Any]:
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Pessoa Teste",
            "email": email,
            "password": PASSWORD,
            "workspace_name": workspace,
        },
        headers=csrf(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def new_client() -> TestClient:
    from app.main import app

    return TestClient(app, base_url="http://testserver")


def upload_csv(client: TestClient, content: bytes, filename: str = "vendas.csv") -> Any:
    return client.post(
        "/api/v1/datasets/upload",
        content=content,
        headers={
            **csrf(client),
            "X-File-Name": filename,
            "Content-Type": "application/octet-stream",
        },
    )


def add_member(workspace_id: str, user_id: str, role: Role) -> None:
    with session_scope() as db:
        db.add(
            WorkspaceMember(
                workspace_id=uuid.UUID(workspace_id), user_id=uuid.UUID(user_id), role=role
            )
        )


SALES_CSV = (
    b"data_venda;vendedor;equipe;produto;quantidade;valor;status\n"
    b"05/01/2025;Ana Souza;Norte;Notebook;2;4.599,90;pago\n"
    b"13/01/2025;Bruno Lima;Sul;Mouse;10;89,90;pago\n"
    b"20/01/2025;Carla Dias;Norte;Monitor;1;1.299,00;pendente\n"
    b"27/01/2025;Ana Souza;Norte;Teclado;x;150,00;pago\n"
    b"\n"
    b"31/01/2025;Diego Melo;Leste;Cadeira\n"
)
