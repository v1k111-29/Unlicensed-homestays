"""Demo sign-in hint on the login page (D96): shown only for configured, existing, active
accounts; values come from the environment only."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HINT_VALUE = "shown-on-login-page"


def _accounts(*pairs: tuple[str, str]) -> list[dict]:
    return [{"role": role, "username": name, "password": HINT_VALUE} for role, name in pairs]


@pytest.mark.django_db
def test_hint_hidden_when_not_configured(client, settings, users) -> None:
    settings.DEMO_LOGIN_ACCOUNTS = []
    body = client.get("/login/").content.decode()
    assert 'id="demo-accounts"' not in body


@pytest.mark.django_db
def test_hint_shows_configured_officer_and_admin(client, settings, users) -> None:
    settings.DEMO_LOGIN_ACCOUNTS = _accounts(("officer", "officer_nil"), ("admin", "admin_one"))
    response = client.get("/login/")
    assert response.status_code == 200
    body = response.content.decode()
    assert 'id="demo-accounts"' in body
    assert "officer_nil" in body and "admin_one" in body
    assert body.count(HINT_VALUE) == 2
    assert "Nilgiris" in body  # the officer's district
    assert "synthetic data only" in body


@pytest.mark.django_db
def test_hint_skips_missing_and_inactive_accounts(client, settings, users) -> None:
    settings.DEMO_LOGIN_ACCOUNTS = _accounts(("officer", "officer_off"), ("admin", "nobody"))
    body = client.get("/login/").content.decode()
    assert 'id="demo-accounts"' not in body
    assert HINT_VALUE not in body


@pytest.mark.django_db
def test_hint_renders_in_tamil(client, settings, users) -> None:
    settings.DEMO_LOGIN_ACCOUNTS = _accounts(("officer", "officer_nil"))
    response = client.get("/ta/login/")
    assert response.status_code == 200
    assert "officer_nil" in response.content.decode()


def _settings_accounts(extra_env: dict[str, str]) -> list[dict]:
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "DATABASE_", "DEMO_"))
    }
    env.update(DJANGO_DEBUG="1", PYTHONPATH=str(ROOT / "src"), **extra_env)
    code = "import json, config.settings as s; print(json.dumps(s.DEMO_LOGIN_ACCOUNTS))"
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_settings_read_complete_pairs_only() -> None:
    accounts = _settings_accounts(
        {
            "DEMO_OFFICER_USERNAME": " demo_officer ",
            "DEMO_OFFICER_PASSWORD": "hint-1",
            "DEMO_ADMIN_USERNAME": "demo_admin",  # no password: not shown
        }
    )
    assert accounts == [{"role": "officer", "username": "demo_officer", "password": "hint-1"}]


def test_settings_default_is_empty() -> None:
    assert _settings_accounts({}) == []
