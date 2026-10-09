"""Settings and DATABASE_URL parsing. No database needed."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from config.dburl import parse_database_url

ROOT = Path(__file__).resolve().parents[1]


def test_parse_full_url() -> None:
    cfg = parse_database_url(
        "postgres://vs_user:p%40ss@db.example:6543/verified_stays?sslmode=require"
    )
    assert cfg["ENGINE"] == "django.db.backends.postgresql"
    assert cfg["NAME"] == "verified_stays"
    assert cfg["USER"] == "vs_user"
    assert cfg["PASSWORD"] == "p@ss"
    assert cfg["HOST"] == "db.example"
    assert cfg["PORT"] == "6543"
    assert cfg["OPTIONS"] == {"sslmode": "require"}


def test_parse_postgresql_scheme_without_port() -> None:
    cfg = parse_database_url("postgresql://u:p@localhost/db")
    assert cfg["PORT"] == "" and "OPTIONS" not in cfg


@pytest.mark.parametrize("url", ["sqlite:///db.sqlite3", "mysql://u:p@h/db", "postgres://u:p@h/"])
def test_parse_rejects_bad_urls(url: str) -> None:
    with pytest.raises(ValueError):
        parse_database_url(url)


def test_production_settings_require_secret_key() -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "DATABASE_"))}
    env["DJANGO_DEBUG"] = "0"
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-c", "import config.settings"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY" in result.stderr


def _import_with_key(key: str, debug: str = "0") -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "DATABASE_"))}
    env.update(
        DJANGO_DEBUG=debug,
        DJANGO_SECRET_KEY=key,
        DJANGO_ALLOWED_HOSTS="a.example",
        DJANGO_CLIENT_IP_HEADER="REMOTE_ADDR",
        PYTHONPATH=str(ROOT / "src"),
    )
    return subprocess.run(
        [sys.executable, "-c", "import config.settings"], env=env, capture_output=True, text=True
    )


@pytest.mark.parametrize(
    "key",
    [
        "change-me",
        "x" * 49,  # one short of the minimum
        "CHANGE-ME-" + "0123456789" * 5,  # long, but still the placeholder
    ],
)
def test_production_settings_refuse_placeholder_or_short_secret_key(key: str) -> None:
    """D89: outside DEBUG a placeholder or < 50-character key stops start-up."""
    result = _import_with_key(key)
    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY" in result.stderr and "placeholder" in result.stderr


def test_production_settings_accept_long_random_key_and_debug_accepts_any() -> None:
    assert _import_with_key("k" * 50).returncode == 0
    assert _import_with_key("change-me", debug="1").returncode == 0


def test_no_missing_migrations() -> None:
    """Models and migrations agree. Uses the autodetector directly so no database is needed."""
    from django.apps import apps
    from django.db.migrations.autodetector import MigrationAutodetector
    from django.db.migrations.loader import MigrationLoader
    from django.db.migrations.state import ProjectState

    loader = MigrationLoader(None, ignore_no_migrations=True)
    changes = MigrationAutodetector(loader.project_state(), ProjectState.from_apps(apps)).changes(
        graph=loader.graph
    )
    assert changes == {}, f"run makemigrations: {sorted(changes)}"
