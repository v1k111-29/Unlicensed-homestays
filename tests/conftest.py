"""Shared test setup.

Tests marked `django_db` need PostgreSQL (DATABASE_URL). When no database is reachable they
are skipped, not failed, so non-DB tests still run on a machine without PostgreSQL.
Set REQUIRE_DB=1 (CI does) to turn "no database" into a hard failure instead of a skip.
"""

import os

import pytest
from django.conf import settings


def _database_problem() -> str | None:
    """Return why the database is unusable, or None if it can be reached."""
    db = settings.DATABASES.get("default")
    # Django fills an empty DATABASES with its dummy backend.
    if not db or db.get("ENGINE", "django.db.backends.dummy") == "django.db.backends.dummy":
        return "DATABASE_URL is not set"
    if db["ENGINE"] != "django.db.backends.postgresql":
        return None  # only PostgreSQL needs a reachability probe
    import psycopg

    last_error = ""
    # pytest-django creates its own test database, so the server is enough: try the configured
    # database, then the default maintenance database.
    for name in (db["NAME"], "postgres"):
        try:
            psycopg.connect(
                dbname=name,
                user=db["USER"] or None,
                password=db["PASSWORD"] or None,
                host=db["HOST"] or None,
                port=db["PORT"] or None,
                connect_timeout=3,
                **db.get("OPTIONS", {}),
            ).close()
            return None
        except psycopg.Error as exc:
            last_error = str(exc).strip().splitlines()[0] if str(exc).strip() else repr(exc)
    return f"PostgreSQL not reachable ({last_error})"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    db_items = [item for item in items if item.get_closest_marker("django_db")]
    if not db_items:
        return
    problem = _database_problem()
    if problem is None:
        return
    if os.environ.get("REQUIRE_DB") == "1":
        raise pytest.UsageError(f"REQUIRE_DB=1 but {problem}")
    skip = pytest.mark.skip(reason=f"needs PostgreSQL: {problem}")
    for item in db_items:
        item.add_marker(skip)
