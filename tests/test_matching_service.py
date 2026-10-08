"""M4 service: run matching on a stored batch and persist run / candidates / results.

Tests marked ``django_db`` need a database (skipped without one; CI runs them on PostgreSQL).
Uses the DEV set only.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.db.models import F
from django.test.utils import CaptureQueriesContext
from django.utils import translation

from accounts.models import District, User
from audit.models import AuditLog
from ingest.load import load_synthetic_set
from listings.models import Listing
from matching import engine
from matching.features import FEATURES
from matching.models import MatchCandidate, MatchResult, MatchRun
from matching.params import CURRENT_VERSION, get_params
from matching.services import MatchingError, run_matching
from registry.models import RegistryEntry, UploadBatch
from reviews.models import ConfirmedPair

DEV = Path(__file__).resolve().parents[1] / "data" / "synthetic" / "out" / "dev"
FORBIDDEN = re.compile(r"illegal|fake|unlicen[cs]ed", re.IGNORECASE)


# ------------------------------------------------------------- no database


def test_band_choices_match_engine_bands() -> None:
    assert {b.value for b in MatchResult.Band} == set(engine.BANDS)
    assert set(engine.STATUS.values()) <= {s.value for s in MatchResult.Status}


@pytest.mark.parametrize("lang", ["en", "ta"])
def test_band_labels_are_neutral(lang: str) -> None:
    with translation.override(lang):
        labels = [str(b.label) for b in MatchResult.Band]
        labels += [str(s.label) for s in MatchResult.Status]
    assert all(not FORBIDDEN.search(label) for label in labels)


def test_reason_codes_are_neutral() -> None:
    src = (Path(engine.__file__)).read_text(encoding="utf-8")
    codes = re.findall(r'\("([a-z_]+)",\)', src) + re.findall(r'append\("([a-z_]+)"\)', src)
    assert codes
    assert not [c for c in codes if FORBIDDEN.search(c)]


# ---------------------------------------------------------------- database

db = pytest.mark.django_db


@pytest.fixture()
def dev_batches() -> tuple[UploadBatch, UploadBatch]:
    load_synthetic_set(DEV, "synthetic-dev", "system:test")
    listings = UploadBatch.objects.get(type="listings", dataset="synthetic-dev")
    registry = UploadBatch.objects.get(type="registry", dataset="synthetic-dev")
    return listings, registry


def _snapshot(run: MatchRun) -> list[tuple]:
    rows = []
    for r in MatchResult.objects.filter(run=run).order_by("listing__external_id"):
        cands = [
            (c.registry_entry.licence_no, c.score, c.rank, c.features)
            for c in MatchCandidate.objects.filter(run=run, listing=r.listing)
            .select_related("registry_entry")
            .order_by("rank")
        ]
        top = r.top_registry_entry.licence_no if r.top_registry_entry else None
        rows.append((r.listing.external_id, r.status, r.band, r.reasons, r.score, top, cands))
    return rows


@db
def test_run_persists_results_candidates_and_audit(dev_batches) -> None:
    listings, registry = dev_batches
    run = run_matching(listings, actor="system:test")

    assert run.params_version == CURRENT_VERSION
    assert run.thresholds["fingerprint"] == get_params().fingerprint()
    assert run.thresholds["t_low"] == get_params().t_low
    assert run.listing_batch == listings and run.registry_batch == registry
    assert run.as_of == date(2026, 4, 1)  # synthetic sets use the generator date (D54)

    n = Listing.objects.filter(batch=listings).count()
    assert MatchResult.objects.filter(run=run).count() == n
    cands = MatchCandidate.objects.filter(run=run)
    assert cands.exists()
    for c in cands[:50]:
        assert set(FEATURES) <= set(c.features)
        assert c.features["blocked_by"]
        assert 0.0 <= c.score <= 1.0
    for r in MatchResult.objects.filter(run=run):
        assert r.status == engine.STATUS[r.band]
        assert r.priority == engine.PRIORITY[r.band]
        assert r.reasons

    entry = AuditLog.objects.get(action="match_run.create", entity_id=str(run.pk))
    assert entry.actor == "system:test"
    assert entry.meta["listings"] == n
    assert sum(entry.meta["bands"].values()) == n


@db
def test_two_runs_give_identical_results(dev_batches) -> None:
    listings, _ = dev_batches
    first = run_matching(listings, actor="system:test")
    second = run_matching(listings, actor="system:test")
    assert first.pk != second.pk
    assert _snapshot(first) == _snapshot(second)


@db
def test_run_never_queries_ground_truth(dev_batches) -> None:
    listings, _ = dev_batches
    with CaptureQueriesContext(connection) as ctx:
        run_matching(listings, actor="system:test")
    assert ctx.captured_queries
    assert not [q for q in ctx.captured_queries if "groundtruth" in q["sql"].lower()]


@db
def test_candidates_stay_in_listing_district(dev_batches) -> None:
    listings, _ = dev_batches
    run = run_matching(listings, actor="system:test")
    mixed = MatchCandidate.objects.filter(run=run).exclude(
        registry_entry__district=F("listing__district")
    )
    assert MatchCandidate.objects.filter(run=run).exists()
    assert not mixed.exists()


def _officer(district: str) -> User:
    return User.objects.create_user(
        username=f"officer-{district.lower()}",
        password="x-test-only-x",
        role=User.Role.OFFICER,
        district=District.objects.get(name_en=district),
    )


@db
def test_officer_cannot_run_on_other_district_listings(dev_batches) -> None:
    listings, _ = dev_batches  # dev listings span all 8 districts
    with pytest.raises(PermissionDenied):
        run_matching(listings, actor=_officer("Nilgiris"))
    assert not MatchRun.objects.exists()


@db
def test_officer_run_on_own_district(dev_batches) -> None:
    _, registry = dev_batches
    nilgiris = District.objects.get(name_en="Nilgiris")
    batch = UploadBatch.objects.create(
        type="listings",
        district=nilgiris,
        dataset="synthetic-dev",
        source_name="officer-test",
        file_sha256="0" * 64,
        row_count=1,
    )
    entry = RegistryEntry.objects.filter(batch=registry, district=nilgiris, status="active")
    entry = entry.order_by("licence_no").first()
    listing = Listing.objects.create(
        title=entry.name,
        locality_text=entry.locality,
        pincode=entry.pincode,
        platform="test",
        batch=batch,
        district=nilgiris,
    )
    officer = _officer("Nilgiris")
    run = run_matching(batch, actor=officer)
    assert run.created_by == officer
    result = MatchResult.objects.get(run=run, listing=listing)
    assert result.top_registry_entry == entry
    assert result.band == engine.MATCHED_SCORE
    assert all(
        c.registry_entry.district_id == nilgiris.pk
        for c in MatchCandidate.objects.filter(run=run).select_related("registry_entry")
    )
    assert AuditLog.objects.filter(action="match_run.create", actor=officer.username).exists()


@db
def test_confirmed_pair_is_not_flagged_again(dev_batches) -> None:
    listings, _ = dev_batches
    run = run_matching(listings, actor="system:test")
    flagged = (
        MatchResult.objects.filter(
            run=run, band=engine.REVIEW_SCORE, top_registry_entry__status="active"
        )
        .order_by("listing__external_id")
        .first()
    )
    assert flagged is not None
    ConfirmedPair.objects.create(listing=flagged.listing, registry_entry=flagged.top_registry_entry)
    again = run_matching(listings, actor="system:test")
    result = MatchResult.objects.get(run=again, listing=flagged.listing)
    assert result.band == engine.MATCHED_CONFIRMED
    assert result.top_registry_entry == flagged.top_registry_entry


@db
def test_wrong_batch_types_and_datasets_are_refused(dev_batches) -> None:
    listings, registry = dev_batches
    with pytest.raises(MatchingError):
        run_matching(registry, actor="system:test")
    with pytest.raises(MatchingError):
        run_matching(listings, actor="system:test", registry_batch=listings)
    other = UploadBatch.objects.create(
        type="registry", dataset="synthetic-other", file_sha256="1" * 64, row_count=0
    )
    with pytest.raises(MatchingError):
        run_matching(listings, actor="system:test", registry_batch=other)
    orphan = UploadBatch.objects.create(
        type="listings", dataset="nothing-here", file_sha256="2" * 64, row_count=0
    )
    with pytest.raises(MatchingError):
        run_matching(orphan, actor="system:test")
