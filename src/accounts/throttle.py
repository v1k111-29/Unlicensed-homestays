"""Failed-login throttling (essentialfeatures.md O1: 5 failed logins -> account/IP limited).

Two independent limits, both "N failures inside a sliding window" (settings.LOGIN_THROTTLE):

- Account: counted from `login_failed` audit rows for the normalised username since the later
  of (window start, last successful login). The audit log is in PostgreSQL, so the count is
  shared by all worker processes and survives restarts. Nothing new is stored.
- IP: counted in the Django cache under an HMAC of the client address. The address itself is
  never written to the database or the cache key (no new personal-data category, AGENTS.md §11).
  With the default per-process memory cache this limit is best-effort per worker (D46).

A throttled attempt does not check the password and is not counted as a failure.
"""

import hashlib
import hmac
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest
from django.utils import timezone

from audit.models import AuditLog

USERNAME_KEY_LEN = 64  # AuditLog.entity_id max_length


def _conf() -> tuple[int, int]:
    conf = settings.LOGIN_THROTTLE
    return int(conf["max_failures"]), int(conf["window_seconds"])


def username_key(username: str) -> str:
    return (username or "").strip().lower()[:USERNAME_KEY_LEN]


def client_ip(request: HttpRequest) -> str:
    """REMOTE_ADDR, or the last entry of a proxy header named in settings (set only behind a
    proxy that appends the real client address, e.g. the hosting platform's load balancer)."""
    header = getattr(settings, "CLIENT_IP_HEADER", "")
    if header:
        value = request.META.get(header, "")
        if value:
            return value.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "")


def _ip_cache_key(request: HttpRequest) -> str:
    digest = hmac.new(
        settings.SECRET_KEY.encode(), client_ip(request).encode(), hashlib.sha256
    ).hexdigest()
    return f"login-fail-ip:{digest}"


def account_failures(username: str) -> int:
    max_failures, window = _conf()
    key = username_key(username)
    since = timezone.now() - timedelta(seconds=window)
    last_success = (
        AuditLog.objects.filter(action="login", actor__iexact=username.strip(), ts__gte=since)
        .order_by("-ts")
        .values_list("ts", flat=True)
        .first()
    )
    if last_success is not None:
        since = max(since, last_success)
    return AuditLog.objects.filter(
        action="login_failed", entity="username", entity_id=key, ts__gt=since
    ).count()


def ip_failures(request: HttpRequest) -> int:
    return int(cache.get(_ip_cache_key(request), 0))


def record_ip_failure(request: HttpRequest) -> None:
    _, window = _conf()
    key = _ip_cache_key(request)
    if cache.add(key, 1, timeout=window):
        return
    try:
        cache.incr(key)
    except ValueError:  # expired between add() and incr()
        cache.set(key, 1, timeout=window)


def blocked_scope(request: HttpRequest, username: str) -> str | None:
    """Return "account" or "ip" if this attempt must be refused, else None."""
    max_failures, _ = _conf()
    if username and account_failures(username) >= max_failures:
        return "account"
    if ip_failures(request) >= max_failures:
        return "ip"
    return None


def describe() -> dict[str, Any]:
    max_failures, window = _conf()
    return {"max_failures": max_failures, "window_minutes": window // 60}
