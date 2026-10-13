"""M6 review fixes: client address behind proxies, login serialisation, absolute session
lifetime, case-insensitive usernames, guarded URLs, tourist-safe template wording."""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.urls import URLPattern, URLResolver, get_resolver

from accounts.models import User
from accounts.throttle import client_ip, login_slot
from audit.models import AuditLog

ROOT = Path(__file__).resolve().parents[1]
MAX = 5
URLS = pytest.mark.urls("tests.m6_urls")


def _post_login(client, username: str, password: str, **meta):
    return client.post("/login/", {"username": username, "password": password}, **meta)


# --- client address behind a proxy (D62) ---


@pytest.mark.django_db
@URLS
def test_spoofed_forwarded_for_is_ignored_without_proxy_header(client, users, password) -> None:
    """CLIENT_IP_HEADER = REMOTE_ADDR: a client-supplied X-Forwarded-For changes nothing."""
    for i in range(MAX):
        _post_login(
            client,
            f"guess_{i}",
            "wrong-password",
            REMOTE_ADDR="10.1.0.1",
            HTTP_X_FORWARDED_FOR=f"203.0.113.{i}",
        )
    response = _post_login(
        client,
        "officer_nil",
        password,
        REMOTE_ADDR="10.1.0.1",
        HTTP_X_FORWARDED_FOR="203.0.113.200",
    )
    assert response.status_code == 429


@pytest.mark.django_db
@URLS
def test_spoofed_prefix_is_ignored_behind_trusted_proxy(client, users, password, settings) -> None:
    """Behind one trusted proxy the address is the entry it appended (rightmost); entries the
    client put in front are ignored."""
    settings.CLIENT_IP_HEADER = "HTTP_X_FORWARDED_FOR"
    settings.TRUSTED_PROXY_HOPS = 1
    for i in range(MAX):
        _post_login(
            client,
            f"guess_{i}",
            "wrong-password",
            REMOTE_ADDR="10.2.0.1",  # the proxy
            HTTP_X_FORWARDED_FOR=f"203.0.113.{i}, 198.51.100.7",
        )
    blocked = _post_login(
        client,
        "officer_nil",
        password,
        REMOTE_ADDR="10.2.0.1",
        HTTP_X_FORWARDED_FOR="203.0.113.99, 198.51.100.7",
    )
    assert blocked.status_code == 429
    # A different real client behind the same proxy is not affected.
    other = _post_login(
        client, "officer_nil", password, REMOTE_ADDR="10.2.0.1", HTTP_X_FORWARDED_FOR="198.51.100.8"
    )
    assert other.status_code == 302


def test_client_ip_hops_and_fallback(rf, settings) -> None:
    settings.CLIENT_IP_HEADER = "HTTP_X_FORWARDED_FOR"
    settings.TRUSTED_PROXY_HOPS = 2
    request = rf.get("/", REMOTE_ADDR="10.3.0.1", HTTP_X_FORWARDED_FOR="1.1.1.1, 2.2.2.2, 3.3.3.3")
    assert client_ip(request) == "2.2.2.2"
    short = rf.get("/", REMOTE_ADDR="10.3.0.1", HTTP_X_FORWARDED_FOR="3.3.3.3")
    assert client_ip(short) == "10.3.0.1"  # fewer entries than trusted hops
    settings.CLIENT_IP_HEADER = "REMOTE_ADDR"
    assert client_ip(request) == "10.3.0.1"


def _import_settings(extra_env: dict[str, str], code: str = "import config.settings"):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "DATABASE_"))}
    env.update(
        DJANGO_DEBUG="0",
        DJANGO_SECRET_KEY="x-test-only-" + "0123456789" * 5,
        DJANGO_ALLOWED_HOSTS="a.example",
        PYTHONPATH=str(ROOT / "src"),
    )
    env.update(extra_env)
    return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)


def test_production_settings_require_client_ip_header() -> None:
    result = _import_settings({})
    assert result.returncode != 0 and "DJANGO_CLIENT_IP_HEADER" in result.stderr


def test_production_proxy_settings() -> None:
    code = (
        "import config.settings as s; "
        "assert s.SECURE_PROXY_SSL_HEADER == ('HTTP_X_FORWARDED_PROTO', 'https'); "
        "assert s.CSRF_TRUSTED_ORIGINS == ['https://a.example']"
    )
    result = _import_settings(
        {
            "DJANGO_CLIENT_IP_HEADER": "HTTP_X_FORWARDED_FOR",
            "DJANGO_CSRF_TRUSTED_ORIGINS": "https://a.example",
        },
        code,
    )
    assert result.returncode == 0, result.stderr


def test_no_proxy_ssl_header_without_proxy() -> None:
    code = "import config.settings as s; assert not hasattr(s, 'SECURE_PROXY_SSL_HEADER')"
    result = _import_settings({"DJANGO_CLIENT_IP_HEADER": "REMOTE_ADDR"}, code)
    assert result.returncode == 0, result.stderr


# --- concurrency: one locked slot per login attempt (D58) ---


@pytest.mark.django_db
def test_login_slot_holds_advisory_locks_on_postgres(rf) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("advisory locks exist on PostgreSQL only; elsewhere the slot is a transaction")
    with login_slot(rf.post("/login/", REMOTE_ADDR="10.4.0.1"), "officer_nil"):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_locks "
                "WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
            )
            assert cursor.fetchone()[0] == 2


@pytest.mark.django_db
def test_login_slot_is_a_transaction(rf) -> None:
    depth = len(connection.savepoint_ids)
    with login_slot(rf.post("/login/"), "officer_nil"):
        assert connection.in_atomic_block
        assert len(connection.savepoint_ids) == depth + 1


# --- absolute session lifetime and usernames ---


@pytest.mark.django_db
@URLS
def test_session_ends_after_absolute_lifetime(client, users, password) -> None:
    _post_login(client, "officer_nil", password)
    assert client.get("/dashboard/").status_code == 200
    session = client.session
    session["login_at"] = int(time.time()) - settings.SESSION_ABSOLUTE_SECONDS - 1
    session.save()
    response = client.get("/dashboard/")
    assert response.status_code == 302 and response["Location"].startswith("/login/")
    assert "_auth_user_id" not in client.session
    assert AuditLog.objects.get(action="logout").meta == {"reason": "session_expired"}
    assert settings.SESSION_ABSOLUTE_SECONDS == 8 * 60 * 60


@pytest.mark.django_db
def test_usernames_are_unique_ignoring_case(users) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(username="OFFICER_NIL", role="admin", password="x")


# --- every routed view is guarded or explicitly public ---

# logout is POST-only and only ends the caller's session; tourist_check is the public M9 page;
# home (M10) only redirects to the tourist check or, once signed in, to the dashboard;
# english_prefix (M10) only redirects /en/<path> to /<path> on this site;
# livez/healthz are the M11 health endpoints (no data, no state change, D81).
PUBLIC_URL_NAMES = {
    "login",
    "logout",
    "tourist_check",
    "home",
    "english_prefix",
    "livez",
    "healthz",
}


def _walk(patterns, prefix: str = ""):
    for entry in patterns:
        if isinstance(entry, URLResolver):
            yield from _walk(entry.url_patterns, prefix + str(entry.pattern))
        elif isinstance(entry, URLPattern):
            yield prefix + str(entry.pattern), entry


def _is_guarded(callback) -> bool:
    from accounts.permissions import CapabilityRequiredMixin

    if getattr(callback, "access_guard", None):
        return True
    view_class = getattr(callback, "view_class", None)
    return view_class is not None and issubclass(view_class, CapabilityRequiredMixin)


def test_every_url_is_guarded_or_allowlisted() -> None:
    routes = list(_walk(get_resolver().url_patterns))
    assert routes, "no routes found"
    unguarded = [
        route
        for route, entry in routes
        if entry.name not in PUBLIC_URL_NAMES and not _is_guarded(entry.callback)
    ]
    assert unguarded == []


def test_route_walk_covers_officer_admin_and_public_routes() -> None:
    """The walk above must actually see the M7/M8 officer and admin routes and the M9 public
    route; a route missing from the resolver would otherwise pass the guard test silently."""
    entries = {entry.name: entry for _, entry in _walk(get_resolver().url_patterns)}
    names = set(entries)
    guarded = {
        "dashboard",
        "upload_listings",
        "runs",
        "run_create",
        "run_detail",
        "queue",
        "case_detail",
        "case_decide",
        "case_evidence",
        "evidence_detail",
        "upload_registry",
        # admin screens (D92, D93)
        "audit_log",
        "account_list",
        "account_create",
        "account_disable",
        "account_enable",
        "account_reset_password",
    }
    public = {"tourist_check", "livez", "healthz"}
    assert guarded | public <= names, sorted((guarded | public) - names)
    # Officer/admin routes are never on the public allowlist and carry a guard themselves.
    assert not guarded & PUBLIC_URL_NAMES
    assert [n for n in sorted(guarded) if not _is_guarded(entries[n].callback)] == []


# --- tourist-safe wording in every template (AGENTS.md rule 2) ---

FORBIDDEN = re.compile(r"\b(illegal|fake|unlicensed)\b", re.IGNORECASE)


def test_no_template_uses_forbidden_words() -> None:
    templates = [p for p in (ROOT / "src").rglob("*.html") if "templates" in p.parts]
    assert templates
    hits = [
        f"{p.relative_to(ROOT)}: {m.group(0)}"
        for p in templates
        for m in FORBIDDEN.finditer(p.read_text(encoding="utf-8"))
    ]
    assert hits == []
