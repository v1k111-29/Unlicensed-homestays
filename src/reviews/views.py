"""Officer review pages (M8, essentialfeatures.md O3-O5): queue, case detail, decision, evidence.

These are plain server-rendered pages and forms with no JavaScript. The URL routes that reach
these views are defined in `config/urls.py`.

Every view is guarded by `require_capability(DECIDE_CASES)`. Every read goes through
`accounts.scoping`, so an object from another district gives a 404 and an audit row. State
changes are POST-only and protected by CSRF. The business rules live in `reviews.services`;
the views only read the request, call the service and choose the page to show.
"""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.permissions import Capability, deny, is_admin, require_capability
from accounts.scoping import get_scoped_or_404, scoped
from listings.models import Listing
from matching import engine
from matching.labels import block_labels, feature_rows, reason_labels
from matching.models import MatchResult
from reviews import services
from reviews.models import ConfirmedPair, EvidencePack, Review

# Number of queue rows shown on one page.
PAGE_SIZE = 50


def _band_label(band: str) -> str:
    """Return the translated label for a band, or the raw value if the band is unknown."""
    return str(MatchResult.Band(band).label) if band in MatchResult.Band.values else band


# ------------------------------------------------------------------ queue


@require_capability(Capability.DECIDE_CASES)
@require_GET
def queue(request: HttpRequest) -> HttpResponse:
    """Show the review queue: filtered, paginated rows plus a count for each band."""
    filters = services.QueueFilters.from_query(request.GET)
    qs, band_counts = services.queue(request.user, filters)
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    decision_labels = dict(Review.Decision.choices)
    rows = [
        {
            "result": r,
            "reasons": ", ".join(reason_labels(r.reasons)),
            "decision": decision_labels.get(r.decision, "") if r.decision else "",
        }
        for r in page.object_list
    ]
    # Keep only the filters that are set, so links to other bands keep the same filters.
    base_query = {
        k: v
        for k, v in {
            "band": filters.band,
            "status": filters.status,
            "state": filters.state,
            "locality": filters.locality,
        }.items()
        if v
    }

    def band_link(band: str) -> str:
        """Return the query string that filters the queue to one band."""
        return "?" + urlencode({**base_query, "band": band})

    band_summary = [
        {
            "key": band,
            "label": _band_label(band),
            "count": band_counts.get(band, 0),
            "url": band_link(band),
            "current": band == filters.band,
        }
        for band in engine.BANDS
    ]
    return render(
        request,
        "reviews/queue.html",
        {
            "filters": filters,
            "page": page,
            "rows": rows,
            "band_summary": band_summary,
            "total_unbanded": sum(band_counts.values()),
            "page_query": urlencode(base_query),
            "band_choices": MatchResult.Band.choices,
            "status_choices": MatchResult.Status.choices,
            "state_choices": [
                (services.STATE_OPEN, _("Open (not decided on the current run)")),
                (services.STATE_DECIDED, _("Decided or confirmed earlier")),
                (services.STATE_ALL, _("All")),
            ],
            "is_admin": is_admin(request.user),
        },
    )


# ------------------------------------------------------------------- case


def _case_context(request: HttpRequest, listing: Listing, **extra: Any) -> dict[str, Any]:
    """Build the template context for the case page.

    `extra` lets the decision view add the submitted form, an error or a conflict. Those keys
    replace the defaults below.
    """
    result = services.current_result(listing)
    candidates = []
    if result is not None:
        for c in services.candidates_for(result):
            features = c.features or {}
            candidates.append(
                {
                    "c": c,
                    "entry": c.registry_entry,
                    "features": feature_rows(features),
                    "blocked_by": ", ".join(block_labels(features.get("blocked_by", []))),
                    "detail": features.get("detail", {}),
                    "is_top": result.top_registry_entry_id == c.registry_entry_id,
                }
            )
    latest = services.latest_review(listing)
    decision_labels = dict(Review.Decision.choices)
    allowed = services.allowed_decisions(request.user)
    # Empty form for a fresh page. The registry entry defaults to the top candidate.
    form = extra.pop("form", None) or {
        "decision": "",
        "reason": "",
        "registry_entry": str(result.top_registry_entry_id or "") if result else "",
    }
    return {
        "listing": listing,
        "result": result,
        "band_label": _band_label(result.band) if result else "",
        "reasons": reason_labels(result.reasons) if result else [],
        "candidates": candidates,
        "history": scoped(Review, request.user)
        .filter(listing=listing)
        .select_related("reviewer", "registry_entry", "run")
        .order_by("-id"),
        "latest": latest,
        "decided_on_current_run": bool(latest and result and latest.run_id == result.run_id),
        "confirmed_pairs": scoped(ConfirmedPair, request.user)
        .filter(listing=listing)
        .select_related("registry_entry"),
        "decision_options": [(v, decision_labels[v]) for v in allowed],
        "suspected_value": str(Review.Decision.SUSPECTED_UNLICENSED),
        "suspected_label": decision_labels[Review.Decision.SUSPECTED_UNLICENSED],
        # The template shows the "suspected" option only when the user is allowed to pick it.
        "can_mark_suspected": str(Review.Decision.SUSPECTED_UNLICENSED) in allowed,
        # These decisions need a registry entry to be chosen first.
        "needs_entry": [str(Review.Decision.CONFIRM_MATCH), str(Review.Decision.REJECT_MATCH)],
        "form": form,
        # The version id the form carries back. The service checks it to catch conflicts.
        "version": latest.pk if latest else 0,
        "evidence_packs": scoped(EvidencePack, request.user)
        .filter(listing=listing)
        .select_related("generated_by")
        .order_by("-id")[:10],
        "max_reason": services.MAX_REASON,
        **extra,
    }


@require_capability(Capability.DECIDE_CASES)
@require_GET
def case_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Show one case: its current result, candidates, history and the decision form."""
    listing = get_scoped_or_404(Listing.objects.select_related("district", "batch"), request, pk=pk)
    return render(request, "reviews/case.html", _case_context(request, listing))


def _int_or_none(value: str | None) -> int | None:
    """Convert a form value to an int, or return None if it is missing or not a number."""
    try:
        return int(value or "")
    except ValueError:
        return None


@require_capability(Capability.DECIDE_CASES)
@require_POST
def case_decide(request: HttpRequest, pk: int) -> HttpResponse:
    """Save an officer decision from the case form.

    On success the user is redirected back to the case with a message. A conflict returns the
    page with status 409 and an error returns it with status 400. The form values are kept so
    the officer does not have to type them again.
    """
    listing = get_scoped_or_404(Listing.objects.select_related("district", "batch"), request, pk=pk)
    form = {
        "decision": request.POST.get("decision", ""),
        "reason": request.POST.get("reason", ""),
        "registry_entry": request.POST.get("registry_entry", ""),
    }
    try:
        services.decide(
            user=request.user,
            listing=listing,
            decision=form["decision"],
            reason=form["reason"],
            registry_entry_id=_int_or_none(form["registry_entry"]),
            expected_run_id=_int_or_none(request.POST.get("run")) or 0,
            expected_review_id=_int_or_none(request.POST.get("version")) or 0,
        )
    except PermissionDenied as exc:
        deny(request, str(exc), listing=listing.pk, decision=form["decision"][:32])
        raise  # unreachable; deny() raises
    except services.DecisionConflict as conflict:
        context = _case_context(request, listing, form=form, conflict=conflict)
        return render(request, "reviews/case.html", context, status=409)
    except services.DecisionError as exc:
        context = _case_context(request, listing, form=form, error=str(exc))
        return render(request, "reviews/case.html", context, status=400)
    messages.success(request, _("Decision saved."))
    return redirect("case_detail", pk=listing.pk)


# --------------------------------------------------------------- evidence


@require_capability(Capability.DECIDE_CASES)
@require_http_methods(["GET", "POST"])
def case_evidence(request: HttpRequest, pk: int) -> HttpResponse:
    """GET: the latest evidence page for this case, or an offer to create one.
    POST: create a new evidence pack (a stored, hashed snapshot) and show it."""
    listing = get_scoped_or_404(Listing.objects.select_related("district", "batch"), request, pk=pk)
    if request.method == "POST":
        try:
            pack = services.create_evidence(listing, request.user)
        except PermissionDenied as exc:
            deny(request, str(exc), listing=listing.pk)
            raise
        return redirect("evidence_detail", pk=pack.pk)
    latest = scoped(EvidencePack, request.user).filter(listing=listing).order_by("-id").first()
    if latest is not None:
        return redirect("evidence_detail", pk=latest.pk)
    return render(request, "reviews/evidence_empty.html", {"listing": listing})


@require_capability(Capability.DECIDE_CASES)
@require_GET
def evidence_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Show one stored evidence pack from its saved snapshot.

    The page also recomputes the hash and shows whether it still matches the stored digest.
    """
    pack = get_scoped_or_404(
        EvidencePack.objects.select_related("listing", "generated_by"), request, pk=pk
    )
    snap = pack.snapshot or {}
    result = snap.get("result") or {}
    decision = snap.get("decision")
    decision_labels = dict(Review.Decision.choices)
    candidates = [
        {**c, "feature_rows": feature_rows(c.get("features", {}))}
        for c in snap.get("candidates", [])
    ]
    return render(
        request,
        "reviews/evidence.html",
        {
            "pack": pack,
            "snap": snap,
            "listing_snap": snap.get("listing", {}),
            "run": snap.get("run"),
            "result": result,
            "band_label": _band_label(result.get("band", "")) if result else "",
            "reasons": reason_labels(result.get("reasons", [])),
            "candidates": candidates,
            "decision": decision,
            "decision_label": decision_labels.get(decision["decision"], "") if decision else "",
            # False would mean the stored snapshot no longer matches its hash.
            "hash_ok": services.snapshot_sha256(snap) == pack.sha256,
            "case_url": reverse("case_detail", args=[pack.listing_id]),
        },
    )
