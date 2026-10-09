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
from matching.models import MatchCandidate, MatchResult, MatchRun, check_same_district
from matching.params import CURRENT_VERSION, get_params
from matching.services import MatchingError, run_matching, run_matching_per_district
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
    nilgiris = District.objects.get(name_en="Nilgiris")
    run = run_matching(listings, actor="system:test", district=nilgiris)

    assert run.district == nilgiris
    assert run.params_version == CURRENT_VERSION
    assert run.thresholds["fingerprint"] == get_params().fingerprint()
    assert run.thresholds["t_low"] == get_params().t_low
    assert run.listing_batch == listings and run.registry_batch == registry
    assert run.as_of == date(2026, 4, 1)  # synthetic sets use the generator date (D54)

    n = Listing.objects.filter(batch=listings, district=nilgiris).count()
    assert MatchResult.objects.filter(run=run).count() == n
    assert not MatchResult.objects.filter(run=run).exclude(listing__district=nilgiris).exists()
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
    assert entry.meta["district"] == "Nilgiris"
    assert sum(entry.meta["bands"].values()) == n


@db
def test_per_district_runs_cover_the_whole_batch(dev_batches) -> None:
    listings, _ = dev_batches
    runs = run_matching_per_district(listings, actor="system:test")
    assert len(runs) == 8  # dev listings span all 8 districts
    assert len({r.district_id for r in runs}) == 8
    total = sum(MatchResult.objects.filter(run=r).count() for r in runs)
    assert total == Listing.objects.filter(batch=listings).count()
    for r in runs:
        assert not MatchResult.objects.filter(run=r).exclude(listing__district=r.district).exists()
    assert AuditLog.objects.filter(action="match_run.create").count() == 8


@db
def test_multi_district_batch_needs_a_district(dev_batches) -> None:
    listings, _ = dev_batches
    with pytest.raises(MatchingError):
        run_matching(listings, actor="system:test")
    assert not MatchRun.objects.exists()


@db
def test_two_runs_give_identical_results(dev_batches) -> None:
    listings, _ = dev_batches
    first = run_matching_per_district(listings, actor="system:test")
    second = run_matching_per_district(listings, actor="system:test")
    assert {r.pk for r in first}.isdisjoint(r.pk for r in second)
    assert [_snapshot(r) for r in first] == [_snapshot(r) for r in second]


@db
def test_run_never_queries_ground_truth(dev_batches) -> None:
    listings, _ = dev_batches
    with CaptureQueriesContext(connection) as ctx:
        run_matching_per_district(listings, actor="system:test")
    assert ctx.captured_queries
    assert not [q for q in ctx.captured_queries if "groundtruth" in q["sql"].lower()]


@db
def test_candidates_stay_in_listing_district(dev_batches) -> None:
    listings, _ = dev_batches
    runs = run_matching_per_district(listings, actor="system:test")
    mixed = MatchCandidate.objects.filter(run__in=runs).exclude(
        registry_entry__district=F("listing__district")
    )
    assert MatchCandidate.objects.filter(run__in=runs).exists()
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
    officer = _officer("Nilgiris")
    with pytest.raises(PermissionDenied):
        run_matching(listings, actor=officer)
    with pytest.raises(PermissionDenied):
        run_matching(listings, actor=officer, district=officer.district)
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
    assert run.district == nilgiris
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
    runs = run_matching_per_district(listings, actor="system:test")
    flagged = (
        MatchResult.objects.filter(
            run__in=runs, band=engine.REVIEW_SCORE, top_registry_entry__status="active"
        )
        .order_by("listing__external_id")
        .first()
    )
    assert flagged is not None
    ConfirmedPair.objects.create(listing=flagged.listing, registry_entry=flagged.top_registry_entry)
    again = run_matching(listings, actor="system:test", district=flagged.listing.district)
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


# ----------------------------------------- district boundary of officer runs (D63)


def _cross_district_setup(users, districts) -> tuple[UploadBatch, RegistryEntry, RegistryEntry]:
    """A Nilgiris listing whose exact twin (licence, name, locality) is registered in Madurai,
    plus a similar Nilgiris entry. All synthetic, made up for this test."""
    reg = UploadBatch.objects.create(type="registry", file_sha256="a1" * 32, row_count=2)
    twin = RegistryEntry.objects.create(
        licence_no="SYN-MDU-70001-A",
        name="Zephyrine Brook Homestay",
        locality="Ooty",
        valid_to=date(2030, 1, 1),
        batch=reg,
        district=districts["mad"],
    )
    own = RegistryEntry.objects.create(
        licence_no="SYN-NLG-70002-B",
        name="Zephyrine Brook Cottage",
        locality="Ooty",
        valid_to=date(2030, 1, 1),
        batch=reg,
        district=districts["nil"],
    )
    lst = UploadBatch.objects.create(
        type="listings",
        file_sha256="a2" * 32,
        row_count=1,
        uploader=users["off_nil"],
        district=districts["nil"],
    )
    Listing.objects.create(
        platform="synthetic",
        title="Zephyrine Brook Homestay",
        locality_text="Ooty",
        claimed_licence_no="SYN-MDU-70001-A",
        batch=lst,
        district=districts["nil"],
    )
    return lst, twin, own


@db
def test_officer_run_never_includes_other_district_registry_entries(users, districts) -> None:
    lst, twin, own = _cross_district_setup(users, districts)
    run = run_matching(lst, actor=users["off_nil"], registry_batch=twin.batch)
    assert run.district == districts["nil"]
    cands = MatchCandidate.objects.filter(run=run)
    assert cands.exists()  # the Nilgiris entry is still compared
    assert twin.pk not in set(cands.values_list("registry_entry_id", flat=True))
    assert set(cands.values_list("registry_entry__district", flat=True)) == {districts["nil"].pk}
    assert MatchResult.objects.get(run=run).top_registry_entry_id != twin.pk


@db
def test_run_refuses_a_cross_district_candidate_from_the_engine(
    users, districts, monkeypatch
) -> None:
    """bulk_create skips save(). The service only loads its own district's registry entries, so an
    engine outcome naming another district's entry cannot be stored: it fails (unknown entry),
    the whole run rolls back and nothing is saved. check_same_district itself refuses the pair."""
    import dataclasses

    from django.core.exceptions import ValidationError

    lst, twin, _own = _cross_district_setup(users, districts)
    real_match = engine.match

    def leaky_match(*args, **kwargs):
        leaked = engine.Candidate(
            registry_id=twin.pk,
            licence_no=twin.licence_no,
            score=0.99,
            rank=1,
            blocked_by=(),
            features={},
        )
        return [
            dataclasses.replace(o, candidates=(leaked,), top_registry_id=twin.pk)
            for o in real_match(*args, **kwargs)
        ]

    monkeypatch.setattr(engine, "match", leaky_match)
    with pytest.raises((KeyError, ValidationError)):
        run_matching(lst, actor=users["off_nil"], registry_batch=twin.batch)
    assert not MatchRun.objects.exists()
    assert not MatchCandidate.objects.exists() and not MatchResult.objects.exists()
    # The guard the service calls before bulk_create refuses the cross-district pair directly.
    run = MatchRun(district=districts["nil"], params_version="t")
    with pytest.raises(ValidationError):
        check_same_district(run, Listing.objects.get(batch=lst), twin)
    check_same_district(run, Listing.objects.get(batch=lst), _own)  # same district: no error
