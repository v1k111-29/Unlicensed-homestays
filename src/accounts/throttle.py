"""Failed-login throttling (essentialfeatures.md O1: 5 failed logins -> account/IP limited).

Two independent limits, both "N failures inside a sliding window" (settings.LOGIN_THROTTLE):

- Account: counted from `login_failed` audit rows for the username since the later of (window
  start, last successful login). Rows store only an HMAC of the normalised username, never the
  typed text (D46, Q19). The audit log is in PostgreSQL, so all workers share the count.
- Address: counted in the database cache (shared by all workers) under an HMAC of the client
  address. The address itself is never written anywhere (AGENTS.md §11).

`login_slot()` serialises concurrent attempts for the same account and address on PostgreSQL
(transaction-scoped advisory locks), so the "count, then check the password, then record the
failure" sequence cannot be raced past the limit. A throttled attempt does not check the
password and is not counted as a failure.
"""

import hashlib
import hmac
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db import connection, transaction
from django.http import HttpRequest
from django.utils import timezone

from audit.models import AuditLog

USERNAME_KEY_LEN = 64


def _conf() -> tuple[int, int]:
    conf = settings.LOGIN_THROTTLE
    return int(conf["max_failures"]), int(conf["window_seconds"])


def _hmac(purpose: str, value: str) -> str:
    message = f"{purpose}:{value}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def username_key(username: str) -> str:
    """The one normalisation used for every username comparison in throttling and audit.
    NFKC folds compatibility look-alikes (e.g. full-width letters); casefold folds case."""
    return unicodedata.normalize("NFKC", username or "").strip().casefold()[:USERNAME_KEY_LEN]


def username_digest(username: str) -> str:
    """HMAC of the normalised username (64 hex chars). Stored instead of the typed text."""
    return _hmac("login-username", username_key(username))


def client_ip(request: HttpRequest) -> str:
    """The client address used for the address limit.

    settings.CLIENT_IP_HEADER is "REMOTE_ADDR" (direct connection) or a proxy header such as
    "HTTP_X_FORWARDED_FOR". With a proxy header, the address is the entry added by the outermost
    trusted proxy: settings.TRUSTED_PROXY_HOPS entries from the right. Entries further left are
    client-supplied and ignored, so spoofing the header does not change the result."""
    header = settings.CLIENT_IP_HEADER
    remote = request.META.get("REMOTE_ADDR", "")
    if header == "REMOTE_ADDR":
        return remote
    hops = max(1, int(settings.TRUSTED_PROXY_HOPS))
    parts = [p.strip() for p in request.META.get(header, "").split(",") if p.strip()]
    if len(parts) < hops:
        return remote  # not set by the trusted proxy chain
    return parts[-hops]


def _ip_cache_key(request: HttpRequest) -> str:
    return f"login-fail-ip:{_hmac('login-ip', client_ip(request))}"


def _lock_id(digest: str) -> int:
    return int.from_bytes(bytes.fromhex(digest[:16]), "big", signed=True)


@contextmanager
def login_slot(request: HttpRequest, username: str) -> Iterator[None]:
    """One transaction per login attempt. On PostgreSQL, also hold advisory locks for the
    account and the address until it ends (sorted order, so two attempts cannot deadlock).
    Other databases (local SQLite checks) get the transaction only."""
    with transaction.atomic():
        if connection.vendor == "postgresql":
            ids = {
                _lock_id(username_digest(username)),
                _lock_id(_hmac("login-ip", client_ip(request))),
            }
            with connection.cursor() as cursor:
                for lock_id in sorted(ids):
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_id])
        yield


def account_failures(username: str) -> int:
    _, window = _conf()
    digest = username_digest(username)
    since = timezone.now() - timedelta(seconds=window)
    last_success = (
        AuditLog.objects.filter(action="login", meta__username_hmac=digest, ts__gte=since)
        .order_by("-ts")
        .values_list("ts", flat=True)
        .first()
    )
    if last_success is not None:
        since = max(since, last_success)
    return AuditLog.objects.filter(
        action="login_failed", entity="username_hmac", entity_id=digest, ts__gt=since
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
    if username_key(username) and account_failures(username) >= max_failures:
        return "account"
    if ip_failures(request) >= max_failures:
        return "ip"
    return None


def describe() -> dict[str, Any]:
    max_failures, window = _conf()
    return {"max_failures": max_failures, "window_minutes": window // 60}
