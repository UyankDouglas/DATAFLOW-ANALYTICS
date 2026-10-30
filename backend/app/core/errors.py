"""Erros de domínio com código estável e mensagem segura para o usuário."""

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "bad_request"
    message = "Requisição inválida."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: Any = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.message)


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_error"
    message = "Os dados enviados são inválidos."


class Unauthorized(AppError):
    status_code = 401
    code = "unauthenticated"
    message = "Sessão ausente ou expirada. Entre novamente."


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"
    message = "Você não tem permissão para esta ação."


class NotFound(AppError):
    status_code = 404
    code = "not_found"
    message = "Recurso não encontrado."


class Conflict(AppError):
    status_code = 409
    code = "conflict"
    message = "A operação conflita com o estado atual do recurso."


class PayloadTooLarge(AppError):
    status_code = 413
    code = "payload_too_large"
    message = "O arquivo excede o tamanho máximo permitido."


class UnsupportedMedia(AppError):
    status_code = 415
    code = "unsupported_media_type"
    message = "Formato de arquivo não suportado."


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Muitas tentativas. Aguarde alguns instantes e tente novamente."


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "Um serviço necessário está indisponível no momento."
