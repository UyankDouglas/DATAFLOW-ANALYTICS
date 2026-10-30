"""Senhas (Argon2id), tokens opacos e CSRF assinado."""

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

# Parâmetros padrão do argon2-cffi (RFC 9106, perfil de baixa memória): Argon2id.
_hasher = PasswordHasher()

# Hash calculado uma vez para equalizar o tempo de resposta quando o e-mail não existe.
_DUMMY_HASH = _hasher.hash("dataflow-timing-equalizer")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _sign(value: str) -> str:
    key = get_settings().secret_key.get_secret_value().encode()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def csrf_token_for_session(session_token_hash: str) -> str:
    """Token CSRF vinculado à sessão: não pode ser reaproveitado em outra sessão."""
    return _sign(f"csrf:session:{session_token_hash}")


def new_anonymous_csrf_token() -> str:
    nonce = secrets.token_urlsafe(16)
    return f"{nonce}.{_sign(f'csrf:anon:{nonce}')}"


def is_valid_anonymous_csrf_token(token: str) -> bool:
    nonce, _, signature = token.partition(".")
    if not nonce or not signature:
        return False
    return hmac.compare_digest(signature, _sign(f"csrf:anon:{nonce}"))


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
