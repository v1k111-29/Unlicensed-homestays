"""Review queue, officer decisions and evidence packs (M8, essentialfeatures.md O3-O5).

This module holds the business rules for the officer review workflow. Views in
`reviews.views` call these functions; they never write rules of their own (AGENTS.md section 8).

Key ideas, in plain words:
- A "case" is a listing. Its current result is the result of the latest matching run that
  covered it.
- The queue lists current results only, ordered by priority, then lower score first (O3).
- A case is "decided" when a review exists for its current run. A listing whose current band is
  `matched_confirmed` is not open either, because the pair was confirmed earlier and is not
  flagged again (O4). A new run on the same listing reopens the case.
- Decisions are new `Review` rows and are never updated. Only an active officer of the
  listing's district may record `suspected_unlicensed`, and only with a written reason
  (AGENTS.md rule 1). The system itself never records any decision.
- Optimistic concurrency: the decision form carries the run id and the id of the latest review
  it was rendered with. If either changed in the meantime, nothing is saved (`DecisionConflict`).
- Every decision and every evidence pack writes one audit entry.

All reads start from `accounts.scoping.scoped()`. Callers pass objects they fetched with
`get_scoped_or_404()`. The district is checked again here before any write.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import PermissionDenied
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Q, QuerySet, Subquery
from django.utils import timezone
from django.utils.translation import gettext as _

import audit
from accounts.permissions import is_officer
from accounts.scoping import can_act_in_district, scoped
from listings.models import Listing
from matching import engine
from matching.features import FEATURES
from matching.models import MatchCandidate, MatchResult
from registry.models import RegistryEntry
from reviews.models import ConfirmedPair, EvidencePack, Review

Decision = Review.Decision

# Longest reason a reviewer may type. Longer text is rejected, not cut short.
MAX_REASON = 2000
# Exact O5 wording. Kept in English inside the stored snapshot (the hash must not depend on
# the viewer's language); the page shows the translated version.
EVIDENCE_STATEMENT = "Supporting evidence for officer review, not a finding."
# Version of the snapshot layout. Bump it if the stored keys change.
SNAPSHOT_SCHEMA = 1

# The three queue views an officer can pick. "open" hides cases already decided on the
# current run; "decided" shows the rest; "all" shows everything.
STATE_OPEN = "open"
STATE_DECIDED = "decided"
STATE_ALL = "all"
STATES = (STATE_OPEN, STATE_DECIDED, STATE_ALL)


class DecisionError(Exception):
    """The decision cannot be saved as submitted. The message is shown to the officer."""


class DecisionConflict(Exception):
    """Someone decided this case, or a new run replaced the result, after the form was shown.

    `latest` is the review that now exists (or None), and `run_changed` says whether the
    matching run changed. The view uses both to explain the conflict.
    """

    def __init__(self, latest: Review | None, run_changed: bool) -> None:
        super().__init__("case changed since the form was shown")
        self.latest = latest
        self.run_changed = run_changed


# ------------------------------------------------------------------ queue


def current_results(user: Any) -> QuerySet[MatchResult]:
    """Return the current result of every listing the user may see.

    The current result is the one from the newest run for that listing. Each row is also
    annotated with the decision on that run (if any) and whether any review exists for it.
    """
    # The newest result for the same listing. Filtering on its pk keeps only one row per listing.
    latest = (
        MatchResult.objects.filter(listing=OuterRef("listing")).order_by("-run_id").values("pk")[:1]
    )
    # Reviews written against the same run as this result.
    reviews_on_run = Review.objects.filter(listing=OuterRef("listing"), run=OuterRef("run"))
    return (
        scoped(MatchResult, user)
        .filter(pk=Subquery(latest))
        .annotate(
            decision=Subquery(reviews_on_run.order_by("-id").values("decision")[:1]),
            decided=Exists(reviews_on_run),
        )
    )


def open_filter() -> Q:
    """Return the filter that selects cases still waiting for an officer.

    A case is open when no review exists for its current run and its band is not
    `matched_confirmed`. Confirmed pairs are not flagged again (O4).
    """
    return Q(decided=False) & ~Q(band=engine.MATCHED_CONFIRMED)


@dataclass(frozen=True)
class QueueFilters:
    """The filters an officer chose on the queue page. Unknown values are dropped to defaults."""

    band: str = ""
    status: str = ""
    state: str = STATE_OPEN
    locality: str = ""

    @classmethod
    def from_query(cls, data: Any) -> QueueFilters:
        """Build filters from request query data, ignoring any value that is not allowed.

        Anything not on the allowed list falls back to "no filter" (or "open" for state), so a
        hand-edited URL cannot ask for a value the page does not offer.
        """
        band = data.get("band", "")
        status = data.get("status", "")
        state = data.get("state", STATE_OPEN)
        return cls(
            band=band if band in MatchResult.Band.values else "",
            status=status if status in MatchResult.Status.values else "",
            state=state if state in STATES else STATE_OPEN,
            # Collapse runs of spaces and cap the length, so the search stays short.
            locality=" ".join(data.get("locality", "").split())[:100],
        )


def queue(user: Any, filters: QueueFilters) -> tuple[QuerySet[MatchResult], dict[str, int]]:
    """Return the filtered, ordered queue and the count per band.

    The band counts ignore the band filter, so the officer can see what that filter hides.
    """
    qs = current_results(user)
    if filters.state == STATE_OPEN:
        qs = qs.filter(open_filter())
    elif filters.state == STATE_DECIDED:
        qs = qs.exclude(open_filter())
    if filters.status:
        qs = qs.filter(status=filters.status)
    if filters.locality:
        qs = qs.filter(listing__locality_text__icontains=filters.locality)
    # Counts are taken before the band filter is applied (see the docstring above).
    band_counts = {
        row["band"]: row["n"] for row in qs.order_by().values("band").annotate(n=Count("id"))
    }
    if filters.band:
        qs = qs.filter(band=filters.band)
    qs = qs.select_related("listing", "listing__district", "top_registry_entry", "run").order_by(
        "priority", F("score").asc(nulls_first=True), "listing_id"
    )
    return qs, band_counts


def dashboard_counts(user: Any) -> dict[str, Any]:
    """Return the headline numbers for the dashboard, limited to what the user may see."""
    results = current_results(user)
    by_band = {
        row["band"]: row["n"]
        for row in results.filter(open_filter()).order_by().values("band").annotate(n=Count("id"))
    }
    return {
        "listings": scoped(Listing, user).count(),
        "with_result": results.count(),
        "open": sum(by_band.values()),
        "open_by_band": [
            {"key": band, "label": MatchResult.Band(band).label, "count": by_band.get(band, 0)}
            for band in engine.BANDS
        ],
        "decisions": scoped(Review, user).filter(run__isnull=False).count(),
        "confirmed_pairs": scoped(ConfirmedPair, user).count(),
        "evidence_packs": scoped(EvidencePack, user).count(),
    }


# ------------------------------------------------------------------- case


def current_result(listing: Listing) -> MatchResult | None:
    """Return the latest result for a listing the caller already fetched through scoping."""
    return (
        MatchResult.objects.filter(listing=listing)
        .select_related("run", "run__registry_batch", "top_registry_entry")
        .order_by("-run_id")
        .first()
    )


def candidates_for(result: MatchResult) -> QuerySet[MatchCandidate]:
    """Return the registry candidates the run scored for this listing, best rank first."""
    return (
        MatchCandidate.objects.filter(run_id=result.run_id, listing_id=result.listing_id)
        .select_related("registry_entry")
        .order_by("rank", "id")
    )


def latest_review(listing: Listing) -> Review | None:
    """Return the newest review of a listing, or None if nobody has decided it yet."""
    return (
        Review.objects.filter(listing=listing)
        .select_related("reviewer", "registry_entry")
        .order_by("-id")
        .first()
    )


def allowed_decisions(user: Any) -> list[str]:
    """Return the decisions the user may record.

    `suspected_unlicensed` is for officers only (rule 1). It is inserted at index 2, so it
    sits between "reject match" and "dismiss" in the order shown on the form.
    """
    values = [Decision.CONFIRM_MATCH, Decision.REJECT_MATCH, Decision.DISMISS]
    if is_officer(user):
        values.insert(2, Decision.SUSPECTED_UNLICENSED)
    return [str(v) for v in values]


@transaction.atomic
def decide(
    *,
    user: Any,
    listing: Listing,
    decision: str,
    reason: str,
    registry_entry_id: int | None,
    expected_run_id: int,
    expected_review_id: int,
) -> Review:
    """Record one officer decision.

    Raises PermissionDenied, DecisionError or DecisionConflict. In those cases nothing is saved.
    The whole function runs in one transaction, so a failure leaves no partial rows behind.
    """
    # Checks run in this order: district first, then role, then input. Changing the order
    # changes which error an officer sees first.
    if not can_act_in_district(user, listing.district_id):
        raise PermissionDenied("out_of_district")
    if decision not in Decision.values:
        raise DecisionError(_("Choose a decision."))
    if decision not in allowed_decisions(user):
        raise PermissionDenied("decision_not_allowed_for_role")
    reason = (reason or "").strip()
    if len(reason) > MAX_REASON:
        raise DecisionError(
            _("The reason is too long (at most %(n)d characters).") % {"n": MAX_REASON}
        )
    # Rule 1: a suspicion must always come with a written reason.
    if decision == Decision.SUSPECTED_UNLICENSED and not reason:
        raise DecisionError(_("A written reason is required for this decision."))

    # Lock the listing row so two officers cannot decide it at the same time (PostgreSQL row
    # lock). After the lock, re-read the state the form was rendered with.
    Listing.objects.select_for_update().filter(pk=listing.pk).first()
    result = current_result(listing)
    if result is None:
        raise DecisionError(_("This listing has not been through a matching run yet."))
    previous = latest_review(listing)
    # If the run or the latest review changed since the form was shown, the officer must
    # reload first. Saving now would decide on stale information.
    run_changed = result.run_id != expected_run_id
    if run_changed or (previous.pk if previous else 0) != expected_review_id:
        raise DecisionConflict(previous, run_changed)

    entry: RegistryEntry | None = None
    if decision in (Decision.CONFIRM_MATCH, Decision.REJECT_MATCH):
        # A match decision must point at one of the candidates the run actually scored.
        # Any other registry id is refused, so an officer cannot decide on an unseen entry.
        candidate = (
            candidates_for(result).filter(registry_entry_id=registry_entry_id).first()
            if registry_entry_id
            else None
        )
        if candidate is None:
            raise DecisionError(_("Choose the registry entry this decision is about."))
        entry = candidate.registry_entry

    # Reviews are only ever added, never edited. The new row supersedes the previous one.
    review = Review.objects.create(
        listing=listing,
        reviewer=user,
        decision=decision,
        reason=reason,
        run=result.run,
        registry_entry=entry,
    )
    # Keep the confirmed-pairs list in step with the decision. Confirmed pairs stop the same
    # pair from being flagged again on later runs (O4).
    pair_change = ""
    if decision == Decision.CONFIRM_MATCH:
        _pair, created = ConfirmedPair.objects.get_or_create(listing=listing, registry_entry=entry)
        pair_change = "added" if created else "kept"
    elif decision == Decision.REJECT_MATCH:
        removed, _detail = ConfirmedPair.objects.filter(
            listing=listing, registry_entry=entry
        ).delete()
        pair_change = "removed" if removed else ""
    # Every decision is written to the audit log (AGENTS.md section 8).
    audit.log(
        user,
        "review.decide",
        "listing",
        listing.pk,
        {
            "review": review.pk,
            "decision": decision,
            "run": result.run_id,
            "band": result.band,
            "registry_entry": entry.pk if entry else None,
            "licence_no": entry.licence_no if entry else "",
            "reason": reason,
            "supersedes": previous.pk if previous else None,
            "confirmed_pair": pair_change,
            "district": listing.district.name_en,
        },
    )
    return review


# --------------------------------------------------------------- evidence


def _canonical(snapshot: dict) -> bytes:
    """Return the snapshot as canonical JSON bytes.

    Keys are sorted and there are no spaces, so the same data always gives the same bytes and
    therefore the same hash.
    """
    return json.dumps(
        snapshot, cls=DjangoJSONEncoder, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def snapshot_sha256(snapshot: dict) -> str:
    """Return the SHA-256 of the canonical JSON form (sorted keys, no spaces, UTF-8)."""
    return hashlib.sha256(_canonical(snapshot)).hexdigest()


def _entry_dict(entry: RegistryEntry) -> dict:
    """Return the fields of one registry entry that an evidence pack stores."""
    return {
        "id": entry.pk,
        "licence_no": entry.licence_no,
        "name": entry.name,
        "address_en": entry.address_en,
        "address_ta": entry.address_ta,
        "locality": entry.locality,
        "pincode": entry.pincode,
        "category": entry.category,
        "valid_from": entry.valid_from,
        "valid_to": entry.valid_to,
        "status": entry.status,
    }


def build_snapshot(listing: Listing, user: Any) -> dict:
    """Collect everything an evidence pack needs about one listing, as plain data.

    The result has no run, result or decision block when those do not exist yet. The return
    value is round-tripped through JSON so the stored copy is exactly what gets hashed.
    """
    result = current_result(listing)
    batch = listing.batch
    snapshot: dict[str, Any] = {
        "schema": SNAPSHOT_SCHEMA,
        "statement": EVIDENCE_STATEMENT,
        "data_notice": "Synthetic demonstration data.",
        "generated_at": timezone.now().replace(microsecond=0),
        "generated_by": user.get_username(),
        "listing": {
            "id": listing.pk,
            "external_id": listing.external_id,
            "platform": listing.platform,
            "ref_url": listing.ref_url,
            "title": listing.title,
            "locality_text": listing.locality_text,
            "pincode": listing.pincode,
            "lat": listing.lat,
            "lng": listing.lng,
            "claimed_licence_no": listing.claimed_licence_no,
            "district": listing.district.name_en,
            "batch": batch.pk if batch else None,
            "batch_sha256": batch.file_sha256 if batch else "",
            "dataset": batch.dataset if batch else "",
        },
        "run": None,
        "result": None,
        "candidates": [],
        "decision": None,
    }
    if result is not None:
        run = result.run
        snapshot["run"] = {
            "id": run.pk,
            "params_version": run.params_version,
            # The parameter fingerprint records which thresholds produced this result.
            "params_fingerprint": (run.thresholds or {}).get("fingerprint", ""),
            "as_of": run.as_of,
            "created_at": run.created_at.replace(microsecond=0),
            "registry_batch": run.registry_batch_id,
            "registry_batch_sha256": run.registry_batch.file_sha256 if run.registry_batch else "",
        }
        snapshot["result"] = {
            "status": result.status,
            "band": result.band,
            "priority": result.priority,
            "score": result.score,
            "reasons": list(result.reasons or []),
            "top_registry_entry": result.top_registry_entry_id,
        }
        snapshot["candidates"] = [
            {
                "rank": c.rank,
                "score": c.score,
                "features": {k: (c.features or {}).get(k) for k in FEATURES},
                "blocked_by": list((c.features or {}).get("blocked_by", [])),
                "registry_entry": _entry_dict(c.registry_entry),
            }
            for c in candidates_for(result)
        ]
    review = latest_review(listing)
    if review is not None:
        snapshot["decision"] = {
            "review": review.pk,
            "decision": review.decision,
            "reviewer": review.reviewer.get_username(),
            "at": review.created_at.replace(microsecond=0),
            "reason": review.reason,
            "registry_entry": review.registry_entry_id,
            "licence_no": review.registry_entry.licence_no if review.registry_entry else "",
            "run": review.run_id,
        }
    # Round-trip through JSON so the stored snapshot is exactly what was hashed.
    return json.loads(_canonical(snapshot))


@transaction.atomic
def create_evidence(listing: Listing, user: Any) -> EvidencePack:
    """Store a new, hashed evidence pack for a listing and write an audit entry.

    Each call creates a new pack; old packs are kept, so the record of what an officer saw
    at a given time stays intact.
    """
    if not can_act_in_district(user, listing.district_id):
        raise PermissionDenied("out_of_district")
    snapshot = build_snapshot(listing, user)
    digest = snapshot_sha256(snapshot)
    pack = EvidencePack.objects.create(
        listing=listing, snapshot=snapshot, sha256=digest, generated_by=user
    )
    audit.log(
        user,
        "evidence.create",
        "evidence_pack",
        pack.pk,
        {
            "listing": listing.pk,
            "sha256": digest,
            "run": (snapshot.get("run") or {}).get("id"),
            "district": listing.district.name_en,
        },
    )
    return pack
