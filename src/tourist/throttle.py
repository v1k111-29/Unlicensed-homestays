"""Rate limit for the public tourist check (security-and-privacy.md §4, D75, D88).

Counts checks per client address in a per-process in-memory cache (the ``tourist_throttle``
cache alias, Django LocMemCache), keyed by an HMAC of the address. Nothing about the address,
not even the HMAC, is written to the database, so it cannot reach a table or a backup
(AGENTS.md rule 5). Trade-off (D88): each Gunicorn worker keeps its own counter, so with N
workers an address gets up to N x ``max_checks`` checks per window, and a restart resets the
counters. The client address comes from ``accounts.throttle.client_ip`` (same proxy settings,
D62).
"""

from __future__ import annotations

import hashlib
import hmac

from django.conf import settings
from django.core.cache import caches
from django.http import HttpRequest

from accounts.throttle import client_ip

CACHE_ALIAS = "tourist_throttle"


def _conf() -> tuple[int, int]:
    """Return (max checks, window in seconds) from the TOURIST_THROTTLE setting."""
    conf = settings.TOURIST_THROTTLE
    return int(conf["max_checks"]), int(conf["window_seconds"])


def cache_key(request: HttpRequest) -> str:
    """Return the cache key for this client address.

    The address is hashed with HMAC and the app's secret key. The raw address never becomes a
    cache key, so it cannot be read back out of the cache store.
    """
    digest = hmac.new(
        settings.SECRET_KEY.encode(),
        f"tourist-ip:{client_ip(request)}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"tourist-check-ip:{digest}"


def allow(request: HttpRequest) -> bool:
    """Count this check; False when the address has used up its checks for the window.

    The first check in a window starts the counter. Later checks add one until the limit.
    """
    max_checks, window = _conf()
    cache = caches[CACHE_ALIAS]
    key = cache_key(request)
    # add() only stores the key if it is new, so it is the first check of this window.
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
