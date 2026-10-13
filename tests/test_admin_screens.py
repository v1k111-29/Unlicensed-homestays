"""Admin screens after M12: audit-log view (O6, D93) and account management (D92).

Synthetic accounts only. No `transactional_db` (D65). Accessibility of these pages is checked
in tests/test_m10_i18n_a11y.py (both languages).
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from accounts import services
from accounts.models import User
from audit.models import AppendOnlyError, AuditLog
from audit.views import META_MAX, meta_summary

pytestmark = pytest.mark.django_db

AUDIT = "/admin/audit/"
ACCOUNTS = "/admin/accounts/"
CREATE = "/admin/accounts/new/"


def _client(user: User | None = None, **kwargs) -> Client:
    client = Client(**kwargs)
    if user is not None:
        client.force_login(user)
    return client


def _url(name: str, pk: int) -> str:
    return f"{ACCOUNTS}{pk}/{name}/"


# ------------------------------------------------------------------ access matrix


def _routes(users) -> list[tuple[str, str]]:
    pk = users["off_mad"].pk
    return [
        ("get", AUDIT),
        ("get", ACCOUNTS),
        ("get", CREATE),
        ("post", CREATE),
        ("post", _url("disable", pk)),
        ("post", _url("enable", pk)),
        ("post", _url("reset-password", pk)),
    ]


def test_anonymous_is_redirected_to_login(users) -> None:
    for method, url in _routes(users):
        response = getattr(Client(), method)(url)
        assert response.status_code == 302, url
        assert response["Location"].startswith("/login/?next="), url


def test_officer_gets_403_and_denial_is_audited(users) -> None:
    client = _client(users["off_nil"])
    for method, url in _routes(users):
        before = AuditLog.objects.filter(action="permission_denied").count()
        assert getattr(client, method)(url).status_code == 403, url
        row = AuditLog.objects.filter(action="permission_denied").order_by("-id").first()
        assert AuditLog.objects.filter(action="permission_denied").count() == before + 1
        assert row.actor == "officer_nil" and row.meta["path"] == url
    assert User.objects.get(pk=users["off_mad"].pk).is_active  # nothing changed
    assert not AuditLog.objects.filter(action__startswith="account.").exists()


def test_admin_reaches_every_screen(users) -> None:
    client = _client(users["admin"])
    for url in (AUDIT, ACCOUNTS, CREATE):
        assert client.get(url).status_code == 200, url


def test_state_changing_routes_refuse_get(users) -> None:
    client = _client(users["admin"])
    for name in ("disable", "enable", "reset-password"):
        assert client.get(_url(name, users["off_mad"].pk)).status_code == 405
    assert client.post(AUDIT).status_code == 405


def test_unknown_account_gives_404(users) -> None:
    client = _client(users["admin"])
    assert client.post(_url("disable", 999999)).status_code == 404


def test_posts_need_csrf(users) -> None:
    client = _client(users["admin"], enforce_csrf_checks=True)
    response = client.post(_url("disable", users["off_mad"].pk))
    assert response.status_code == 403
    assert User.objects.get(pk=users["off_mad"].pk).is_active


def test_nav_links_for_admins_only(users) -> None:
    admin_html = _client(users["admin"]).get("/dashboard/").content.decode()
    officer_html = _client(users["off_nil"]).get("/dashboard/").content.decode()
    for url in (AUDIT, ACCOUNTS):
        assert f'href="{url}"' in admin_html
        assert url not in officer_html


# ------------------------------------------------------------------ audit log screen


def _entries(html: str) -> list[str]:
    return re.findall(r'<td class="mono">([a-z_.]+)</td>\s*<td class="mono">', html)


def test_audit_log_newest_first_and_read_does_not_write(users) -> None:
    client = _client(users["admin"])
    AuditLog.objects.create(actor="system:test", action="aaa_first", entity="x", entity_id="1")
    AuditLog.objects.create(actor="system:test", action="zzz_second", entity="x", entity_id="2")
    count = AuditLog.objects.count()
    html = client.get(AUDIT).content.decode()
    client.get(AUDIT, {"action": "aaa_first"})
    client.get(AUDIT, {"page": "2"})
    assert AuditLog.objects.count() == count  # plain reads write nothing (D93)
    actions = _entries(html)
    assert actions.index("zzz_second") < actions.index("aaa_first")


def test_audit_log_filters(users) -> None:
    client = _client(users["admin"])
    old = AuditLog.objects.create(actor="alpha_admin", action="registry_upload", entity="upload")
    AuditLog.objects.create(actor="beta_officer", action="decision", entity="listing")
    html = client.get(AUDIT, {"actor": "ALPHA"}).content.decode()
    assert "alpha_admin" in html and "beta_officer" not in html
    html = client.get(AUDIT, {"action": "decision"}).content.decode()
    assert "beta_officer" in html and "alpha_admin" not in html
    html = client.get(AUDIT, {"entity": "upload"}).content.decode()
    assert "alpha_admin" in html and "beta_officer" not in html
    today = timezone.localdate(old.ts)
    html = client.get(AUDIT, {"date_from": today.isoformat()}).content.decode()
    assert "alpha_admin" in html
    tomorrow = (today + timedelta(days=1)).isoformat()
    html = client.get(AUDIT, {"date_from": tomorrow}).content.decode()
    assert "alpha_admin" not in html and "empty-state" in html
    yesterday = (today - timedelta(days=1)).isoformat()
    html = client.get(AUDIT, {"date_to": yesterday}).content.decode()
    assert "alpha_admin" not in html
    html = client.get(AUDIT, {"date_from": today.isoformat(), "date_to": today.isoformat()})
    assert "alpha_admin" in html.content.decode()


def test_audit_log_invalid_filters_show_error_state(users) -> None:
    client = _client(users["admin"])
    response = client.get(AUDIT, {"date_from": "2026-13-40"})
    assert response.status_code == 400
    html = response.content.decode()
    assert 'role="alert"' in html and "Enter a date as YYYY-MM-DD." in html
    response = client.get(AUDIT, {"date_from": "2026-05-02", "date_to": "2026-05-01"})
    assert response.status_code == 400
    assert "The end date is before the start date." in response.content.decode()
    assert client.get(AUDIT, {"action": "no_such_action"}).status_code == 400


def test_audit_log_pagination_keeps_filters(users) -> None:
    AuditLog.objects.bulk_create(
        AuditLog(actor="pager_bot", action="page_test", entity="x", entity_id=str(i))
        for i in range(120)
    )
    client = _client(users["admin"])
    html = client.get(AUDIT, {"actor": "pager_bot"}).content.decode()
    assert len(re.findall(r'<td class="mono">page_test</td>', html)) == 50
    assert "Page 1 of 3" in html
    assert 'href="?actor=pager_bot&amp;page=2"' in html
    html = client.get(AUDIT, {"actor": "pager_bot", "page": "3"}).content.decode()
    assert len(re.findall(r'<td class="mono">page_test</td>', html)) == 20
    assert 'href="?actor=pager_bot&amp;page=2"' in html


def test_audit_log_has_no_write_controls(users) -> None:
    client = _client(users["admin"])
    html = client.get(AUDIT).content.decode()
    main = html.split('<main id="main"', 1)[1].split("</main>", 1)[0]
    assert 'method="post"' not in main.lower()
    assert re.findall(r"<button\b", main) == ["<button"]  # the filter submit only
    assert not re.search(r"\b(delete|edit|remove|undo)\b", main, re.IGNORECASE)


def test_audit_log_hides_secrets_and_addresses(users) -> None:
    AuditLog.objects.create(
        actor="system:test",
        action="leak_test",
        entity="x",
        meta={
            "password": "pw-should-not-show",
            "token": "tok-should-not-show",
            "client_ip": "198.51.100.23",
            "note": "from 203.0.113.9 by someone@example.org",
            "url": "postgres://user:hunter2@db.example/x",
        },
    )
    # A failed sign-in is logged with an HMAC entity id.
    Client().post("/login/", {"username": "officer_nil", "password": "wrong-password"})
    html = _client(users["admin"]).get(AUDIT).content.decode()
    for leaked in (
        "pw-should-not-show",
        "tok-should-not-show",
        "198.51.100.23",
        "203.0.113.9",
        "someone@example.org",
        "hunter2",
        "127.0.0.1",
        "wrong-password",
    ):
        assert leaked not in html, leaked
    assert "[hidden]" in html and "[ip]" in html
    assert ">hashed<" in html  # failed sign-in entity id is labelled


def test_meta_summary_is_truncated_and_escaped(users) -> None:
    text = meta_summary({"note": "x" * 500})
    assert len(text) == META_MAX and text.endswith("…")
    AuditLog.objects.create(
        actor="<script>x</script>", action="xss_test", entity="x", meta={"n": "<b>bold</b>"}
    )
    html = _client(users["admin"]).get(AUDIT).content.decode()
    assert "<script>x</script>" not in html and "<b>bold</b>" not in html
    assert "&lt;script&gt;" in html


def test_audit_rows_stay_append_only(users) -> None:
    """The screen only reads: the model guards are unchanged and the view code has no write
    call on audit rows."""
    from pathlib import Path

    import audit.views

    source = Path(audit.views.__file__).read_text(encoding="utf-8")
    assert not re.search(r"\.(delete|update|save|create|bulk_create)\(", source)
    row = AuditLog.objects.create(actor="system:test", action="guard_test", entity="x")
    with pytest.raises(AppendOnlyError):
        row.delete()
    with pytest.raises(AppendOnlyError):
        AuditLog.objects.all().update(action="changed")


# ------------------------------------------------------------------ account management


def _password_on_page(html: str) -> str:
    return re.search(r'<span class="mono" lang="en">([^<]+)</span>', html).group(1)


def test_create_officer_shows_password_once_and_audits(users, password) -> None:
    client = _client(users["admin"])
    response = client.post(
        CREATE,
        {"username": "new_officer", "role": "officer", "district": users["off_nil"].district_id},
    )
    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]
    html = response.content.decode()
    new_password = _password_on_page(html)
    assert len(new_password) >= 20
    user = User.objects.get(username="new_officer")
    assert user.role == "officer" and user.district_id == users["off_nil"].district_id
    assert user.check_password(new_password) and user.is_active
    row = AuditLog.objects.get(action="account.create")
    assert row.actor == "admin_one" and row.entity_id == str(user.pk)
    assert row.meta == {
        "username": "new_officer",
        "role": "officer",
        "district": "Nilgiris",
        "via": "web",
    }
    # The password is nowhere else: not in the session, the audit log or a later page.
    assert new_password not in str(dict(client.session))
    assert not AuditLog.objects.filter(meta__icontains=new_password).exists()
    assert new_password not in client.get(ACCOUNTS).content.decode()
    assert new_password not in response.get("Location", "")
    # The new account can sign in with it.
    signed = Client().post("/login/", {"username": "new_officer", "password": new_password})
    assert signed.status_code == 302


@pytest.mark.parametrize(
    ("data", "field_error"),
    [
        ({"username": "", "role": "officer"}, "Enter a username."),
        ({"username": "OFFICER_NIL", "role": "admin"}, "already exists"),
        ({"username": "has space", "role": "admin"}, "English letters"),
        ({"username": "x" * 65, "role": "admin"}, "at most 64"),
        ({"username": "nodistrict", "role": "officer"}, "Officers need a district."),
        ({"username": "admin_d", "role": "admin", "district": "NIL"}, "not tied to a district"),
        ({"username": "badrole", "role": "superuser"}, "Select a valid choice"),
    ],
)
def test_create_refuses_bad_input(users, data, field_error) -> None:
    if data.get("district") == "NIL":
        data = {**data, "district": users["off_nil"].district_id}
    before = User.objects.count()
    response = _client(users["admin"]).post(CREATE, data)
    assert response.status_code == 400
    html = response.content.decode()
    assert field_error in html and 'role="alert"' in html
    assert User.objects.count() == before
    assert not AuditLog.objects.filter(action="account.create").exists()


def test_disable_and_enable_are_audited_and_end_sessions(users, password) -> None:
    officer = _client(users["off_mad"])
    assert officer.get("/dashboard/").status_code == 200
    admin = _client(users["admin"])
    response = admin.post(_url("disable", users["off_mad"].pk))
    assert response.status_code == 302 and response["Location"] == ACCOUNTS
    assert not User.objects.get(pk=users["off_mad"].pk).is_active
    row = AuditLog.objects.get(action="account.disable")
    assert row.actor == "admin_one" and row.entity_id == str(users["off_mad"].pk)
    assert "password" not in row.meta
    # The disabled officer's session ends and sign-in is refused.
    assert officer.get("/dashboard/").status_code == 302
    login = Client().post("/login/", {"username": "officer_mad", "password": password})
    assert login.status_code == 200 and "_auth_user_id" not in login.client.session
    # Disabling again changes nothing and writes nothing.
    admin.post(_url("disable", users["off_mad"].pk))
    assert AuditLog.objects.filter(action="account.disable").count() == 1
    admin.post(_url("enable", users["off_mad"].pk))
    assert User.objects.get(pk=users["off_mad"].pk).is_active
    assert AuditLog.objects.filter(action="account.enable").count() == 1


def test_admin_cannot_disable_self_or_last_admin(users) -> None:
    admin = users["admin"]
    client = _client(admin)
    response = client.post(_url("disable", admin.pk), follow=True)
    assert "You cannot disable your own account." in response.content.decode()
    assert User.objects.get(pk=admin.pk).is_active
    assert not AuditLog.objects.filter(action="account.disable").exists()


def test_last_active_admin_guard(users) -> None:
    admin = users["admin"]
    second = User.objects.create_user(username="admin_two", role="admin", password="x")
    services.set_active(admin, second.pk, False)
    assert not User.objects.get(pk=second.pk).is_active
    # Only admin_one is active now; even a request made in admin_two's name (a stale
    # session) cannot disable the last active admin.
    with pytest.raises(services.AccountError, match="last active administrator"):
        services.set_active(second, admin.pk, False)
    assert User.objects.get(pk=admin.pk).is_active


def test_list_shows_role_district_status_and_no_delete(users) -> None:
    html = _client(users["admin"]).get(ACCOUNTS).content.decode()
    for name in ("officer_nil", "officer_mad", "admin_one", "officer_off"):
        assert name in html
    assert "Nilgiris" in html and "Disabled" in html and "Never" in html
    assert "(you)" in html
    assert _url("disable", users["admin"].pk) not in html  # no self-disable button
    assert _url("enable", users["inactive"].pk) in html
    assert not re.search(r"\bdelete\b", html, re.IGNORECASE)


def test_reset_password_shows_once_and_ends_sessions(users, password) -> None:
    officer = _client(users["off_nil"])
    admin = _client(users["admin"])
    response = admin.post(_url("reset-password", users["off_nil"].pk))
    assert response.status_code == 200 and "no-store" in response["Cache-Control"]
    new_password = _password_on_page(response.content.decode())
    user = User.objects.get(pk=users["off_nil"].pk)
    assert user.check_password(new_password) and not user.check_password(password)
    row = AuditLog.objects.get(action="account.reset_password")
    assert row.meta == {"username": "officer_nil"}
    assert not AuditLog.objects.filter(meta__icontains=new_password).exists()
    assert new_password not in str(dict(admin.session))
    assert officer.get("/dashboard/").status_code == 302  # old session ended


def test_admin_resetting_own_password_stays_signed_in(users) -> None:
    admin = _client(users["admin"])
    assert admin.post(_url("reset-password", users["admin"].pk)).status_code == 200
    assert admin.get(ACCOUNTS).status_code == 200


def test_generated_passwords_pass_validators_and_differ() -> None:
    from django.contrib.auth.password_validation import validate_password

    seen = {services.generate_password() for _ in range(50)}
    assert len(seen) == 50
    for pw in list(seen)[:5]:
        validate_password(pw)
        assert re.fullmatch(r"[A-Za-z2-9]{5}(-[A-Za-z2-9]{5}){3}", pw)


def test_command_shares_the_service_rules(users, monkeypatch, fast_hasher, password) -> None:
    from django.core.management import CommandError

    monkeypatch.setenv("ADMIN_SCREEN_PW", password)
    with pytest.raises(CommandError, match="already exists"):
        call_command(
            "create_account", "Officer_Nil", "--role", "admin", "--password-env", "ADMIN_SCREEN_PW"
        )
    with pytest.raises(CommandError, match="English letters"):
        call_command(
            "create_account", "bad name", "--role", "admin", "--password-env", "ADMIN_SCREEN_PW"
        )
    call_command(
        "create_account", "cmd_admin", "--role", "admin", "--password-env", "ADMIN_SCREEN_PW"
    )
    row = AuditLog.objects.get(action="user_created")
    assert row.actor == "system:create_account" and "password" not in row.meta
    assert row.meta["via"] == "command"
