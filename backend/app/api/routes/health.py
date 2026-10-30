from fastapi import APIRouter
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import get_engine
from app.core.redis import get_redis
from app.services import storage

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", summary="Processo ativo")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", summary="Dependências disponíveis")
def ready() -> JSONResponse:
    checks: dict[str, bool] = {}
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = True
    except SQLAlchemyError:
        checks["database"] = False
    try:
        checks["redis"] = bool(get_redis().ping())
    except RedisError:
        checks["redis"] = False
    checks["storage"] = storage.is_available()
    healthy = all(checks.values())
    return JSONResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks},
        status_code=200 if healthy else 503,
    )
