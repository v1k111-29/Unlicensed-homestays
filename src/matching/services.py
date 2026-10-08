"""Run matching on a listings batch and store the results (data-and-matching.md §5-7).

Django glue only: records are built from the database, ``matching.engine.match`` does the
work, and the outcome is written to ``match_runs`` / ``match_candidates`` /
``match_results`` in one transaction with one audit entry.

The service never reads ``matching.GroundTruth`` (D35); a test checks the SQL it issues.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

import audit
from accounts.models import District, User
from listings.models import Listing
from matching import engine
from matching.gazetteer import Gazetteer
from matching.models import MatchCandidate, MatchResult, MatchRun, check_same_district
from matching.params import CURRENT_VERSION, get_params
from matching.records import ListingRecord, RegistryRecord
from registry.models import RegistryEntry, UploadBatch
from reviews.models import ConfirmedPair

# The synthetic sets were generated "as of" this date (generator REFERENCE_DATE, M1).
# Judging their licence validity on today's date would turn active entries into expired
# ones as time passes, so synthetic datasets default to it (D54).
SYNTHETIC_AS_OF = date(2026, 4, 1)


class MatchingError(ValueError):
    """The run cannot start (wrong batch type, no registry to match against, ...)."""


_gazetteer: Gazetteer | None = None


def default_gazetteer() -> Gazetteer:
    global _gazetteer
    if _gazetteer is None:
        _gazetteer = Gazetteer.load()
    return _gazetteer


def current_registry_batch(listing_batch: UploadBatch) -> UploadBatch:
    """Registry batch a listings batch is matched against (Q15, Q17 accepted defaults):
    the latest registry batch with the same ``dataset`` label. Real uploads have an empty
    label, so they use the latest real registry upload; synthetic sets never mix."""
    batch = (
        UploadBatch.objects.filter(type=UploadBatch.Type.REGISTRY, dataset=listing_batch.dataset)
        .order_by("-created_at", "-id")
        .first()
    )
    if batch is None:
        label = listing_batch.dataset or "real uploads"
        raise MatchingError(f"no registry batch for dataset '{label}'")
    return batch


def default_as_of(listing_batch: UploadBatch) -> date:
    if listing_batch.dataset.startswith("synthetic-"):
        return SYNTHETIC_AS_OF
    return timezone.localdate()


def _check_scope(actor: Any, listings: list[Listing]) -> None:
    """District scoping, server side (AGENTS.md rule 7): an officer may only run matching
    on listings of their own district."""
    if not isinstance(actor, User) or actor.role == User.Role.ADMIN:
        return
    if actor.district_id is None or any(x.district_id != actor.district_id for x in listings):
        raise PermissionDenied("listings outside the officer's district")


def _check_district(actor: Any, district: District) -> None:
    """The run district must be the officer's own (AGENTS.md rule 7)."""
    if isinstance(actor, User) and actor.role != User.Role.ADMIN:
        if actor.district_id != district.pk:
            raise PermissionDenied("run district outside the officer's district")


def _f(value: Any) -> float | None:
    return None if value is None else float(value)


def _registry_record(e: RegistryEntry) -> RegistryRecord:
    return RegistryRecord(
        id=e.pk,
        licence_no=e.licence_no,
        name=e.name,
        district=e.district.name_en,
        locality=e.locality,
        valid_to=e.valid_to,
        address_en=e.address_en,
        address_ta=e.address_ta,
        pincode=e.pincode,
        lat=_f(e.lat),
        lng=_f(e.lng),
        category=e.category,
        valid_from=e.valid_from,
        status=e.status,
    )


def _listing_record(x: Listing) -> ListingRecord:
    return ListingRecord(
        id=x.pk,
        title=x.title,
        locality_text=x.locality_text,
        district=x.district.name_en,
        pincode=x.pincode,
        lat=_f(x.lat),
        lng=_f(x.lng),
        claimed_licence_no=x.claimed_licence_no,
    )


def batch_districts(listing_batch: UploadBatch) -> list[District]:
    """Districts that have listings in ``listing_batch``, by name."""
    ids = Listing.objects.filter(batch=listing_batch).values_list("district_id", flat=True)
    return list(District.objects.filter(pk__in=ids).order_by("name_en"))


def run_matching(
    listing_batch: UploadBatch,
    *,
    actor: Any,
    district: District | None = None,
    registry_batch: UploadBatch | None = None,
    params_version: str = CURRENT_VERSION,
    as_of: date | None = None,
    gazetteer: Gazetteer | None = None,
) -> MatchRun:
    """Match the listings of ``listing_batch`` in one district and store one run (D63:
    one district per run). Returns the run.

    ``district`` may be left out when the batch covers one district only; a multi-district
    batch needs it (or use ``run_matching_per_district``). ``actor`` is a ``User`` or a
    ``"system:<tool>"`` string (audit actor).
    """
    if listing_batch.type != UploadBatch.Type.LISTINGS:
        raise MatchingError("listing_batch must be a listings batch")
    if registry_batch is None:
        registry_batch = current_registry_batch(listing_batch)
    elif registry_batch.type != UploadBatch.Type.REGISTRY:
        raise MatchingError("registry_batch must be a registry batch")
    if registry_batch.dataset != listing_batch.dataset:
        raise MatchingError("listings and registry come from different datasets (Q15)")

    all_listings = list(
        Listing.objects.filter(batch=listing_batch).select_related("district").order_by("id")
    )
    _check_scope(actor, all_listings)
    if district is None:
        present = {x.district_id for x in all_listings}
        if len(present) > 1:
            raise MatchingError("the batch covers several districts; name one")
        district = listing_batch.district or (all_listings[0].district if all_listings else None)
        if district is None:
            raise MatchingError("the batch has no listings")
    _check_district(actor, district)

    params = get_params(params_version)
    as_of = as_of or default_as_of(listing_batch)
    gazetteer = gazetteer or default_gazetteer()

    listings = [x for x in all_listings if x.district_id == district.pk]
    if not listings:
        raise MatchingError("the batch has no listings in this district")
    entries = list(
        RegistryEntry.objects.filter(batch=registry_batch, district=district)
        .select_related("district")
        .order_by("id")
    )
    confirmed: dict[int, list[int]] = {}
    for listing_id, entry_id in (
        ConfirmedPair.objects.filter(listing__in=listings)
        .order_by("listing_id", "registry_entry_id")
        .values_list("listing_id", "registry_entry_id")
    ):
        confirmed.setdefault(listing_id, []).append(entry_id)

    outcomes = engine.match(
        [_listing_record(x) for x in listings],
        [_registry_record(e) for e in entries],
        params,
        as_of=as_of,
        gazetteer=gazetteer,
        confirmed=confirmed,
    )

    listing_by_id = {x.pk: x for x in listings}
    entry_by_id = {e.pk: e for e in entries}
    user = actor if isinstance(actor, User) else None
    counts = {band: 0 for band in engine.BANDS}
    with transaction.atomic():
        run = MatchRun.objects.create(
            district=district,
            params_version=params.version,
            thresholds={**params.snapshot(), "fingerprint": params.fingerprint()},
            created_by=user,
            listing_batch=listing_batch,
            registry_batch=registry_batch,
            as_of=as_of,
        )
        candidates = []
        results = []
        for o in outcomes:
            counts[o.band] += 1
            listing = listing_by_id[o.listing_id]
            for c in o.candidates:
                entry = entry_by_id[c.registry_id]
                # bulk_create skips save(); the same-district check runs here (D63).
                check_same_district(run, listing, entry)
                candidates.append(
                    MatchCandidate(
                        run=run,
                        listing=listing,
                        registry_entry=entry,
                        score=c.score,
                        features={**c.features, "blocked_by": list(c.blocked_by)},
                        rank=c.rank,
                    )
                )
            top = entry_by_id[o.top_registry_id] if o.top_registry_id is not None else None
            check_same_district(run, listing, top)
            results.append(
                MatchResult(
                    run=run,
                    listing=listing,
                    status=o.status,
                    band=o.band,
                    reasons=list(o.reasons),
                    top_registry_entry=top,
                    score=o.score,
                    priority=o.priority,
                )
            )
        MatchCandidate.objects.bulk_create(candidates, batch_size=1000)
        MatchResult.objects.bulk_create(results, batch_size=1000)
        # Automatic "Matched" results are audit-logged (§7) through this one run entry.
        audit.log(
            actor,
            "match_run.create",
            "match_run",
            run.pk,
            {
                "district": district.name_en,
                "params_version": params.version,
                "fingerprint": params.fingerprint(),
                "listing_batch": listing_batch.pk,
                "registry_batch": registry_batch.pk,
                "dataset": listing_batch.dataset,
                "as_of": as_of.isoformat(),
                "listings": len(outcomes),
                "candidates": len(candidates),
                "bands": counts,
                "auto_matched_listings": [
                    o.listing_id for o in outcomes if o.band == engine.MATCHED_LICENCE
                ],
            },
        )
    return run


def run_matching_per_district(
    listing_batch: UploadBatch, *, actor: Any, **kwargs: Any
) -> list[MatchRun]:
    """One run per district present in ``listing_batch`` (admin and synthetic loads), all in
    one transaction: either every district run is stored or none is."""
    with transaction.atomic():
        return [
            run_matching(listing_batch, actor=actor, district=d, **kwargs)
            for d in batch_districts(listing_batch)
        ]
