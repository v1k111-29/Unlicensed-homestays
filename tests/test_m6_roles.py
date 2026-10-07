"""Role matrix (docs/security-and-privacy.md §1) and capability guards on views."""

import pytest
from django.contrib.auth.models import AnonymousUser

from accounts.models import User
from accounts.permissions import Capability, capabilities_for, has_capability
from audit.models import AuditLog

C = Capability
# Written out independently of accounts.permissions, straight from the spec table.
SPEC = {
    "anonymous": {C.TOURIST_CHECK},
    "officer": {C.TOURIST_CHECK, C.UPLOAD_LISTINGS, C.RUN_MATCHING, C.DECIDE_CASES},
    "admin": set(C),
}


def _user(role: str, district_id: int | None = 1, active: bool = True) -> User:
    return User(username=f"u_{role}", role=role, district_id=district_id, is_active=active)


@pytest.mark.parametrize("capability", list(C))
@pytest.mark.parametrize("who", ["anonymous", "officer", "admin"])
def test_role_matrix_matches_spec(who: str, capability: Capability) -> None:
    user = AnonymousUser() if who == "anonymous" else _user(who)
    assert has_capability(user, capability) is (capability in SPEC[who])


def test_officer_without_district_has_no_capabilities() -> None:
    assert capabilities_for(_user("officer", district_id=None)) == frozenset()


def test_inactive_user_has_no_capabilities() -> None:
    assert capabilities_for(_user("admin", active=False)) == frozenset()
    assert capabilities_for(_user("officer", active=False)) == frozenset()


def test_superuser_flag_grants_nothing_extra() -> None:
    officer = _user("officer")
    officer.is_superuser = officer.is_staff = True
    assert capabilities_for(officer) == SPEC["officer"]


def test_unknown_role_has_no_capabilities() -> None:
    assert capabilities_for(_user("auditor")) == frozenset()


# --- views ---

PROTECTED = ["/dashboard/", "/t/listings/", "/t/registry/", "/t/users/", "/t/run/", "/t/audit/"]


@pytest.mark.django_db
@pytest.mark.urls("tests.m6_urls")
@pytest.mark.parametrize("url", PROTECTED)
def test_anonymous_is_redirected_to_login(client, url: str) -> None:
    response = client.get(url)
    assert response.status_code == 302
    assert response["Location"] == f"/login/?next={url}"


# (url, officer allowed, admin allowed)
VIEW_MATRIX = [
    ("/t/listings/", True, True),
    ("/t/run/", True, True),
    ("/t/registry/", False, True),
    ("/t/users/", False, True),
    ("/t/audit/", False, True),
]


@pytest.mark.django_db
@pytest.mark.urls("tests.m6_urls")
@pytest.mark.parametrize(("url", "officer_ok", "admin_ok"), VIEW_MATRIX)
def test_view_access_by_role(client, users, url: str, officer_ok: bool, admin_ok: bool) -> None:
    for key, allowed in (("off_nil", officer_ok), ("admin", admin_ok)):
        client.force_login(users[key])
        assert client.get(url).status_code == (200 if allowed else 403), (key, url)


@pytest.mark.django_db
@pytest.mark.urls("tests.m6_urls")
def test_permission_denial_is_audited(client, users) -> None:
    client.force_login(users["off_nil"])
    assert client.get("/t/audit/").status_code == 403
    row = AuditLog.objects.get(action="permission_denied")
    assert row.actor == "officer_nil"
    assert row.meta["reason"] == "missing_capability"
    assert row.meta["capability"] == "view_audit"
    assert row.meta["path"] == "/t/audit/"


@pytest.mark.django_db
@pytest.mark.urls("tests.m6_urls")
def test_inactive_user_cannot_sign_in(client, users, password) -> None:
    response = client.post("/login/", {"username": "officer_off", "password": password})
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
@pytest.mark.urls("tests.m6_urls")
def test_dashboard_shows_role_and_district(client, users) -> None:
    client.force_login(users["off_nil"])
    body = client.get("/dashboard/").content.decode()
    assert "officer_nil" in body and "Nilgiris" in body and "Madurai" not in body
