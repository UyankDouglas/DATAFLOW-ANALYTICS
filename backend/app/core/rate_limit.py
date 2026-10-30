"""Rate limiting por janela fixa em Redis.

Falha aberta (registra aviso) quando o Redis está indisponível, para não derrubar o login
inteiro por causa do limitador. A decisão está registrada em docs/security.md.
"""

import hashlib
import logging

from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.errors import RateLimited
from app.core.redis import get_redis

logger = logging.getLogger(__name__)


def _key(scope: str, identity: str) -> str:
    digest = hashlib.sha256(identity.encode()).hexdigest()[:32]
    return f"rl:{scope}:{digest}"


def hit(scope: str, identity: str, *, limit: int, window_seconds: int) -> None:
    """Conta uma tentativa e lança RateLimited se o limite da janela foi excedido."""
    if not get_settings().rate_limit_enabled:
        return
    key = _key(scope, identity)
    try:
        redis = get_redis()
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        count, _ = pipe.execute()
        ttl = redis.ttl(key)
    except RedisError:
        logger.warning("rate_limit_unavailable", extra={"scope": scope})
        return
    if int(count) > limit:
        raise RateLimited(details={"retry_after_seconds": max(int(ttl), 1)})


def reset(scope: str, identity: str) -> None:
    try:
        get_redis().delete(_key(scope, identity))
    except RedisError:
        logger.warning("rate_limit_unavailable", extra={"scope": scope})
