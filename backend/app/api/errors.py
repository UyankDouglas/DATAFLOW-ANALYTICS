"""Respostas de erro padronizadas: {"error": {code, message, details}, "request_id"}."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.core.errors import AppError, RateLimited, Unauthorized
from app.core.logging import request_id_var

logger = logging.getLogger(__name__)

_HTTP_MESSAGES = {
    404: ("not_found", "Recurso não encontrado."),
    405: ("method_not_allowed", "Método não permitido."),
    413: ("payload_too_large", "Conteúdo excede o tamanho permitido."),
}


def error_payload(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {
        "error": {"code": code, "message": message, "details": details},
        "request_id": request_id_var.get(),
    }


def _translate(error: Any) -> str:
    """Mensagens do Pydantic em pt-BR; validadores próprios já escrevem em português."""
    kind = error.get("type", "")
    ctx = error.get("ctx") or {}
    message = str(error.get("msg", ""))
    if kind == "value_error":
        if "email address" in message:
            return "Informe um e-mail válido."
        return message.removeprefix("Value error, ")
    translations = {
        "missing": "Campo obrigatório.",
        "string_too_short": f"Informe ao menos {ctx.get('min_length')} caractere(s).",
        "string_too_long": f"Máximo de {ctx.get('max_length')} caracteres.",
        "too_short": f"Informe ao menos {ctx.get('min_length')} item(ns).",
        "too_long": f"Máximo de {ctx.get('max_length')} itens.",
        "int_parsing": "Informe um número inteiro.",
        "int_type": "Informe um número inteiro.",
        "bool_parsing": "Informe verdadeiro ou falso.",
        "uuid_parsing": "Identificador inválido.",
        "greater_than_equal": f"O valor mínimo é {ctx.get('ge')}.",
        "less_than_equal": f"O valor máximo é {ctx.get('le')}.",
        "literal_error": f"Valor não permitido. Opções: {ctx.get('expected')}.",
        "enum": f"Valor não permitido. Opções: {ctx.get('expected')}.",
        "string_pattern_mismatch": "Formato inválido.",
        "json_invalid": "JSON inválido.",
    }
    return translations.get(kind, message)


def _validation_details(exc: RequestValidationError) -> list[dict[str, Any]]:
    details = []
    for error in exc.errors():
        message = _translate(error)
        details.append(
            {
                "field": ".".join(str(part) for part in error.get("loc", ()) if part != "body"),
                "message": message,
                "type": error.get("type"),
            }
        )
    return details


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        response = JSONResponse(
            error_payload(exc.code, exc.message, exc.details), status_code=exc.status_code
        )
        if isinstance(exc, Unauthorized):
            # Sessão inválida: remove o cookie para permitir novo login com CSRF anônimo.
            response.delete_cookie(get_settings().session_cookie_name, path="/")
        if isinstance(exc, RateLimited) and isinstance(exc.details, dict):
            response.headers["Retry-After"] = str(exc.details.get("retry_after_seconds", 60))
        return response

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            error_payload(
                "validation_error", "Os dados enviados são inválidos.", _validation_details(exc)
            ),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = _HTTP_MESSAGES.get(exc.status_code, ("http_error", "Erro na requisição."))
        return JSONResponse(error_payload(code, message), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", extra={"error_type": type(exc).__name__})
        return JSONResponse(
            error_payload("internal_error", "Erro interno inesperado. Tente novamente mais tarde."),
            status_code=500,
        )
