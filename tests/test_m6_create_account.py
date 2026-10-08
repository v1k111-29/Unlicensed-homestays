"""`create_account` management command (synthetic demo accounts)."""

import pytest
from django.core.management import CommandError, call_command

from accounts.models import User
from audit.models import AuditLog

pytestmark = pytest.mark.django_db


@pytest.fixture
def env_password(monkeypatch, fast_hasher, password) -> str:
    monkeypatch.setenv("M6_TEST_PASSWORD", password)
    return "M6_TEST_PASSWORD"


def test_creates_officer_with_district_and_audits(env_password) -> None:
    call_command(
        "create_account",
        "demo_officer",
        "--role",
        "officer",
        "--district",
        "nilgiris",
        "--password-env",
        env_password,
    )
    user = User.objects.get(username="demo_officer")
    assert user.role == "officer" and user.district.name_en == "Nilgiris"
    row = AuditLog.objects.get(action="user_created")
    assert row.actor == "system:create_account" and row.entity_id == str(user.pk)


def test_creates_admin_without_district(env_password) -> None:
    call_command("create_account", "demo_admin", "--role", "admin", "--password-env", env_password)
    assert User.objects.get(username="demo_admin").district is None


@pytest.mark.parametrize(
    "args",
    [
        ["x_officer", "--role", "officer"],  # officer without district
        ["x_officer", "--role", "officer", "--district", "Atlantis"],
        ["x_admin", "--role", "admin", "--district", "Nilgiris"],
    ],
)
def test_rejects_bad_arguments(env_password, args: list[str]) -> None:
    with pytest.raises(CommandError):
        call_command("create_account", *args, "--password-env", env_password)
    assert not User.objects.exists()


def test_rejects_weak_password(monkeypatch, fast_hasher) -> None:
    monkeypatch.setenv("M6_WEAK", "123")
    with pytest.raises(CommandError):
        call_command("create_account", "weak", "--role", "admin", "--password-env", "M6_WEAK")
    assert not User.objects.exists()
