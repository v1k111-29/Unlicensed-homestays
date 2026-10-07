"""Login, logout, session settings, audit entries and failed-login throttling (M6)."""

import pytest
from django.conf import settings

from audit.models import AppendOnlyError, AuditLog

pytestmark = [pytest.mark.django_db, pytest.mark.urls("tests.m6_urls")]


def _login(client, username: str, password: str, ip: str = "10.0.0.1"):
    return client.post("/login/", {"username": username, "password": password}, REMOTE_ADDR=ip)


def _signed_in(client) -> bool:
    return "_auth_user_id" in client.session


# --- login / logout ---


def test_login_page_renders(client) -> None:
    response = client.get("/login/")
    assert response.status_code == 200
    body = response.content.decode()
    assert '<html lang="en">' in body
    assert 'autocomplete="current-password"' in body
    assert "csrfmiddlewaretoken" in body


def test_valid_login_redirects_to_dashboard(client, users, password) -> None:
    response = _login(client, "officer_nil", password)
    assert response.status_code == 302 and response["Location"] == "/dashboard/"
    assert _signed_in(client)


def test_login_honours_safe_next_only(client, users, password) -> None:
    response = client.post(
        "/login/?next=/t/run/", {"username": "officer_nil", "password": password, "next": "/t/run/"}
    )
    assert response["Location"] == "/t/run/"
    client.logout()
    response = client.post(
        "/login/",
        {"username": "officer_nil", "password": password, "next": "https://evil.example/"},
    )
    assert response["Location"] == "/dashboard/"


def test_wrong_password_does_not_sign_in(client, users) -> None:
    response = _login(client, "officer_nil", "wrong-password")
    assert response.status_code == 200
    assert not _signed_in(client)
    assert 'role="alert"' in response.content.decode()


def test_logout_requires_post_and_ends_session(client, users) -> None:
    client.force_login(users["off_nil"])
    assert client.get("/logout/").status_code == 405
    response = client.post("/logout/")
    assert response.status_code == 302 and response["Location"] == "/login/"
    assert not _signed_in(client)
    assert client.get("/dashboard/").status_code == 302


# --- audit entries ---


def test_login_success_is_audited(client, users, password) -> None:
    _login(client, "officer_nil", password)
    row = AuditLog.objects.get(action="login")
    assert (row.actor, row.entity, row.entity_id) == (
        "officer_nil",
        "user",
        str(users["off_nil"].pk),
    )
    assert row.meta == {"role": "officer"}


def test_logout_is_audited(client, users, password) -> None:
    _login(client, "officer_nil", password)
    client.post("/logout/")
    row = AuditLog.objects.get(action="logout")
    assert row.actor == "officer_nil" and row.entity_id == str(users["off_nil"].pk)


def test_failed_login_is_audited_without_ip_or_password(client, users) -> None:
    _login(client, "Officer_NIL", "wrong-password", ip="10.9.8.7")
    row = AuditLog.objects.get(action="login_failed")
    assert (row.actor, row.entity, row.entity_id) == ("anonymous", "username", "officer_nil")
    stored = f"{row.actor} {row.entity_id} {row.meta}"
    assert "10.9.8.7" not in stored and "wrong-password" not in stored


def test_failed_login_for_unknown_user_is_audited(client, users) -> None:
    _login(client, "nobody_here", "whatever-pass")
    assert AuditLog.objects.filter(action="login_failed", entity_id="nobody_here").count() == 1


def test_auth_audit_rows_cannot_be_updated_or_deleted(client, users, password) -> None:
    _login(client, "officer_nil", "wrong-password")
    _login(client, "officer_nil", password)
    client.post("/logout/")
    rows = list(AuditLog.objects.filter(action__in=["login_failed", "login", "logout"]))
    assert len(rows) == 3
    for row in rows:
        row.meta = {"tampered": True}
        with pytest.raises(AppendOnlyError):
            row.save()
        with pytest.raises(AppendOnlyError):
            row.delete()
    with pytest.raises(AppendOnlyError):
        AuditLog.objects.filter(action="login").update(actor="someone_else")
    with pytest.raises(AppendOnlyError):
        AuditLog.objects.filter(action="logout").delete()
    assert AuditLog.objects.filter(action__in=["login_failed", "login", "logout"]).count() == 3
    assert not AuditLog.objects.filter(actor="someone_else").exists()


# --- throttling: 5 failures in the window lock the account and the address ---

MAX = 5


def test_account_locked_after_five_failures(client, users, password) -> None:
    for _ in range(MAX):
        assert _login(client, "officer_nil", "wrong-password").status_code == 200
    response = _login(client, "officer_nil", password)  # correct password, still refused
    assert response.status_code == 429
    assert not _signed_in(client)
    assert "Please wait and try again." in response.content.decode()
    row = AuditLog.objects.get(action="login_throttled")
    assert row.entity_id == "officer_nil" and row.meta == {"scope": "account"}
    # A throttled attempt is not counted as a failed password check.
    assert AuditLog.objects.filter(action="login_failed").count() == MAX


def test_account_lock_applies_from_any_address(client, users, password) -> None:
    for i in range(MAX):
        _login(client, "officer_nil", "wrong-password", ip=f"10.0.1.{i}")
    assert _login(client, "officer_nil", password, ip="10.0.2.1").status_code == 429


def test_account_lock_is_case_insensitive(client, users, password) -> None:
    names = ["officer_nil", "OFFICER_NIL", "Officer_Nil", "officer_NIL", " officer_nil "]
    for i, name in enumerate(names):
        _login(client, name, "wrong-password", ip=f"10.0.3.{i}")
    assert _login(client, "officer_nil", password, ip="10.0.4.1").status_code == 429


def test_four_failures_do_not_lock(client, users, password) -> None:
    for _ in range(MAX - 1):
        _login(client, "officer_nil", "wrong-password")
    assert _login(client, "officer_nil", password).status_code == 302


def test_successful_login_resets_account_count(client, users, password) -> None:
    for _ in range(MAX - 1):
        _login(client, "officer_nil", "wrong-password", ip="10.0.5.1")
    assert _login(client, "officer_nil", password, ip="10.0.5.2").status_code == 302
    client.post("/logout/")
    for _ in range(MAX - 1):
        _login(client, "officer_nil", "wrong-password", ip="10.0.5.3")
    assert _login(client, "officer_nil", password, ip="10.0.5.4").status_code == 302


def test_lock_does_not_affect_other_accounts(client, users, password) -> None:
    for i in range(MAX):
        _login(client, "officer_nil", "wrong-password", ip=f"10.0.6.{i}")
    assert _login(client, "officer_mad", password, ip="10.0.7.1").status_code == 302


def test_address_locked_after_five_failures(client, users, password) -> None:
    for i in range(MAX):
        _login(client, f"guess_{i}", "wrong-password", ip="10.0.8.8")
    response = _login(client, "officer_mad", password, ip="10.0.8.8")
    assert response.status_code == 429
    assert not _signed_in(client)
    assert AuditLog.objects.get(action="login_throttled").meta == {"scope": "ip"}
    # Another address can still sign in to the same account.
    assert _login(client, "officer_mad", password, ip="10.0.8.9").status_code == 302


def test_empty_form_does_not_count_as_failure(client, users, password) -> None:
    for _ in range(MAX + 2):
        client.post("/login/", {"username": "", "password": ""}, REMOTE_ADDR="10.0.9.9")
    assert _login(client, "officer_nil", password, ip="10.0.9.9").status_code == 302


def test_lock_expires_after_window(client, users, password, settings) -> None:
    for _ in range(MAX):
        _login(client, "officer_nil", "wrong-password")
    settings.LOGIN_THROTTLE = {"max_failures": MAX, "window_seconds": 0}
    assert _login(client, "officer_nil", password, ip="10.0.10.1").status_code == 302


# --- session settings ---


def test_session_cookie_settings() -> None:
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"
    assert settings.SESSION_COOKIE_AGE <= 60 * 60
    assert settings.SESSION_SAVE_EVERY_REQUEST is True
    assert settings.SESSION_EXPIRE_AT_BROWSER_CLOSE is True
    assert settings.PASSWORD_HASHERS[0].endswith("Argon2PasswordHasher")
    assert settings.X_FRAME_OPTIONS == "DENY"
    assert "django.middleware.csrf.CsrfViewMiddleware" in settings.MIDDLEWARE


def test_login_rotates_session_key(client, users, password) -> None:
    client.get("/login/")
    client.cookies["sessionid"] = "attacker-chosen-session-key"
    _login(client, "officer_nil", password)
    assert client.session.session_key != "attacker-chosen-session-key"


def test_csrf_enforced_on_login(users, password) -> None:
    from django.test import Client

    strict = Client(enforce_csrf_checks=True)
    response = strict.post("/login/", {"username": "officer_nil", "password": password})
    assert response.status_code == 403
