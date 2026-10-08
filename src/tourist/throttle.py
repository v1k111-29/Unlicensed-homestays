"""Rate limit for the public tourist check (security-and-privacy.md §4, D60).

Counts checks per client address in the database cache (shared by all workers), keyed by an
HMAC of the address, as the M6 login throttle does. The address itself is never stored. The
client address comes from ``accounts.throttle.client_ip`` (same proxy settings, D50).
"""

from __future__ import annotations

import hashlib
import hmac

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest

from accounts.throttle import client_ip


def _conf() -> tuple[int, int]:
    conf = settings.TOURIST_THROTTLE
    return int(conf["max_checks"]), int(conf["window_seconds"])


def cache_key(request: HttpRequest) -> str:
    digest = hmac.new(
        settings.SECRET_KEY.encode(),
        f"tourist-ip:{client_ip(request)}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"tourist-check-ip:{digest}"


def allow(request: HttpRequest) -> bool:
    """Count this check; False when the address has used up its checks for the window."""
    max_checks, window = _conf()
    key = cache_key(request)
    if cache.add(key, 1, timeout=window):
        return True
    count = int(cache.get(key, 0))
    if count >= max_checks:
        return False
    try:
        cache.incr(key)
    except ValueError:  # expired between add() and incr()
        cache.set(key, 1, timeout=window)
    return True
