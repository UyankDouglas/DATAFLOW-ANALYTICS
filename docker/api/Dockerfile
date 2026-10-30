# syntax=docker/dockerfile:1.7
# Imagem única do backend: API, worker Celery, beat, migrations e setup do armazenamento.

FROM ghcr.io/astral-sh/uv:0.13.6 AS uv

FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app

FROM base AS deps
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

FROM base AS runtime
COPY --from=deps /opt/venv /opt/venv
COPY backend/ ./
RUN useradd --system --uid 10001 --home-dir /var/lib/dataflow --create-home dataflow \
    && rm -rf tests
USER dataflow
ENV PATH="/opt/venv/bin:$PATH" \
    WORK_DIR=/var/lib/dataflow
EXPOSE 8000
# --proxy-headers: o IP real do cliente vem do proxy reverso (única porta exposta).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]

# Alvo para rodar testes e lint dentro de contêiner (inclui dependências de desenvolvimento).
FROM base AS dev
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-install-project
COPY backend/ ./
ENV PATH="/opt/venv/bin:$PATH" WORK_DIR=/tmp/dataflow
CMD ["pytest", "-q"]
