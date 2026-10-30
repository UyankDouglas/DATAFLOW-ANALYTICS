"""Middlewares ASGI puros (não consomem o corpo, preservando uploads em streaming)."""

import logging
import time
import uuid
from http.cookies import SimpleCookie

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.core.logging import request_id_var
from app.core.security import (
    constant_time_equals,
    csrf_token_for_session,
    hash_token,
    is_valid_anonymous_csrf_token,
)

logger = logging.getLogger("app.access")

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"cache-control", b"no-store"),
]


def _headers(scope: Scope) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


def _cookies(headers: dict[str, str]) -> dict[str, str]:
    jar: SimpleCookie = SimpleCookie()
    try:
        jar.load(headers.get("cookie", ""))
    except Exception:  # cookie malformado é tratado como ausente
        return {}
    return {key: morsel.value for key, morsel in jar.items()}


async def _reject(send: Send, status: int, code: str, message: str) -> None:
    import json

    body = json.dumps(
        {
            "error": {"code": code, "message": message, "details": None},
            "request_id": request_id_var.get(),
        },
        ensure_ascii=False,
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), *SECURITY_HEADERS],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RequestContextMiddleware:
    """Request id, cabeçalhos de segurança e log de acesso sem dados pessoais."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = _headers(scope).get("x-request-id", "")
        request_id = (
            incoming if 8 <= len(incoming) <= 64 and incoming.isalnum() else uuid.uuid4().hex
        )
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = list(message.get("headers", []))
                existing = {k.lower() for k, _ in headers}
                headers += [(k, v) for k, v in SECURITY_HEADERS if k not in existing]
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            logger.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status_holder["status"],
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            request_id_var.reset(token)


class CSRFMiddleware:
    """Double-submit cookie assinado + verificação de Origin para métodos não seguros."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") not in UNSAFE_METHODS
            or not scope.get("path", "").startswith("/api/")
        ):
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        headers = _headers(scope)
        origin = headers.get("origin")
        if origin and origin not in settings.allowed_origins:
            await _reject(send, 403, "csrf_origin", "Origem da requisição não permitida.")
            return

        cookies = _cookies(headers)
        header_token = headers.get(settings.csrf_header_name.lower(), "")
        cookie_token = cookies.get(settings.csrf_cookie_name, "")
        if (
            not header_token
            or not cookie_token
            or not constant_time_equals(header_token, cookie_token)
        ):
            await _reject(
                send, 403, "csrf_failed", "Token CSRF ausente ou inválido. Recarregue a página."
            )
            return

        session_token = cookies.get(settings.session_cookie_name)
        if session_token:
            valid = constant_time_equals(
                header_token, csrf_token_for_session(hash_token(session_token))
            )
        else:
            valid = is_valid_anonymous_csrf_token(header_token)
        if not valid:
            await _reject(
                send, 403, "csrf_failed", "Token CSRF ausente ou inválido. Recarregue a página."
            )
            return
        await self.app(scope, receive, send)
