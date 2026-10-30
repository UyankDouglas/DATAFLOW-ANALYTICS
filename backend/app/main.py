"""Aplicação FastAPI do DataFlow Analytics."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.api.errors import register_error_handlers
from app.api.middleware import CSRFMiddleware, RequestContextMiddleware
from app.api.routes import auth, datasets, health, jobs, workspaces
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services import storage

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.validate_for_production()
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        storage.ensure_bucket()
    except storage.StorageError:
        # A API sobe mesmo assim; /health/ready reporta o armazenamento indisponível.
        logger.warning("storage_unavailable_on_startup")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="DataFlow Analytics API",
        version="0.1.0",
        description="API de importação, processamento e análise de dados.",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    register_error_handlers(app)
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(RequestContextMiddleware)

    api = APIRouter(prefix="/api/v1")
    for module in (auth, workspaces, datasets, jobs):
        api.include_router(module.router)
    app.include_router(api)
    app.include_router(health.router)
    return app


app = create_app()
