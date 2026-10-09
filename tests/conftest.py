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


# --- M6 shared fixtures (auth, roles, district scoping). Tests using them must carry the
# `django_db` marker so they skip cleanly without a database. The login address throttle uses
# the database cache, so its entries roll back with each test. Do not use `transactional_db`:
# the audit_log TRUNCATE trigger makes its teardown fail on PostgreSQL. ---

PASSWORD = "synthetic-test-pass-91"  # test-only value, not a real credential


@pytest.fixture
def password() -> str:
    return PASSWORD


@pytest.fixture
def fast_hasher(settings) -> None:
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def districts(db) -> dict:
    from accounts.models import District

    return {
        "nil": District.objects.get(name_en="Nilgiris"),
        "mad": District.objects.get(name_en="Madurai"),
    }


@pytest.fixture
def users(districts, fast_hasher) -> dict:
    """Synthetic accounts: one officer per district, one admin, one inactive officer."""
    from accounts.models import User

    def make(username: str, role: str, district=None, **extra) -> User:
        return User.objects.create_user(
            username=username, password=PASSWORD, role=role, district=district, **extra
        )

    return {
        "off_nil": make("officer_nil", "officer", districts["nil"]),
        "off_mad": make("officer_mad", "officer", districts["mad"]),
        "admin": make("admin_one", "admin"),
        "inactive": make("officer_off", "officer", districts["nil"], is_active=False),
    }


@pytest.fixture
def district_data(users, districts) -> dict:
    """One row of every district-bearing model in each of the two districts."""
    from datetime import date

    from listings.models import Listing
    from matching.models import GroundTruth, MatchCandidate, MatchResult, MatchRun
    from registry.models import RegistryEntry, UploadBatch
    from reviews.models import ConfirmedPair, EvidencePack, Review

    rows: dict = {}
    for key, district in districts.items():
        officer = users[f"off_{key}"]
        reg_batch = UploadBatch.objects.create(
            type="registry", file_sha256=f"r{key}", row_count=1, dataset="m6-test"
        )
        lst_batch = UploadBatch.objects.create(
            type="listings",
            file_sha256=f"l{key}",
            row_count=1,
            uploader=officer,
            district=district,
            dataset="m6-test",
        )
        entry = RegistryEntry.objects.create(
            licence_no=f"SYN-{key}-1",
            name=f"Synthetic Stay {key}",
            locality="Synthetic locality",
            valid_to=date(2030, 1, 1),
            batch=reg_batch,
            district=district,
        )
        listing = Listing.objects.create(
            platform="synthetic",
            title=f"Synthetic listing {key}",
            locality_text="Synthetic locality",
            batch=lst_batch,
            district=district,
        )
        run = MatchRun.objects.create(
            district=district, params_version="m6-test", created_by=officer
        )
        rows[key] = {
            "District": district,
            "User": officer,
            "UploadBatch": lst_batch,
            "RegistryEntry": entry,
            "Listing": listing,
            "MatchRun": run,
            "MatchCandidate": MatchCandidate.objects.create(
                run=run, listing=listing, registry_entry=entry, score=0.5, rank=1
            ),
            "MatchResult": MatchResult.objects.create(
                run=run, listing=listing, status="needs_review", top_registry_entry=entry
            ),
            "GroundTruth": GroundTruth.objects.create(
                listing=listing, true_registry_entry=entry, type="clean"
            ),
            "Review": Review.objects.create(
                listing=listing, reviewer=officer, decision="dismiss", reason="synthetic"
            ),
            "ConfirmedPair": ConfirmedPair.objects.create(listing=listing, registry_entry=entry),
            "EvidencePack": EvidencePack.objects.create(
                listing=listing, snapshot={}, sha256="0" * 64, generated_by=officer
            ),
        }
    return rows


@pytest.fixture(autouse=True)
def _reset_language():
    """LocaleMiddleware activates the request language for the whole thread; a test that
    requests a /ta/ page would otherwise leave later tests (e.g. error-message checks) in Tamil."""
    from django.utils import translation

    yield
    translation.activate(settings.LANGUAGE_CODE)
