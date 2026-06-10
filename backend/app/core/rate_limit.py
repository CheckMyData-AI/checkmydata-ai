"""Rate limiting configuration using slowapi.

With ``REDIS_URL`` set (and the ``redis`` package installed) slowapi counts
against Redis so limits hold across processes/dynos (T-SEC-7). Otherwise it
falls back to per-process in-memory counting.
"""

import importlib.util
import logging

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

logger = logging.getLogger(__name__)


def _storage_uri() -> str:
    if settings.redis_url:
        if importlib.util.find_spec("redis") is not None:
            return settings.redis_url
        logger.warning(
            "REDIS_URL is set but the 'redis' package is not installed; "
            "rate limits fall back to per-process memory storage"
        )
    return "memory://"


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["60/minute"],
    storage_uri=_storage_uri(),
)
