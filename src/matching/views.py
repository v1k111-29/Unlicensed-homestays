"""Matching runs (M7, essentialfeatures.md O3): start a run on a listings batch and show its
summary (results per band). The review queue and case pages are M8.

What this file is for: the web pages where an officer starts a matching run, lists past
runs, and opens one run's summary. Views only handle the request and the response. The
matching itself happens in ``services.run_matching``.

Who calls it: the URL configuration (``config/urls.py``) routes requests here.

All reads go through `accounts.scoping`; `matching.services.run_matching` checks the district
again on the server side and writes the run's audit entry.
"""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from accounts.permissions import Capability, deny, is_admin, require_capability
from accounts.scoping import get_scoped_or_404, scoped
from matching import engine
from matching.models import MatchCandidate, MatchResult, MatchRun
from matching.services import MatchingError, run_matching, run_matching_per_district
from registry.models import RESERVED_DATASETS, UploadBatch


def _runnable_batches() -> Any:
    """Listings batches; the reserved synthetic test set is never run from the UI (rule 9)."""
    # The exclude() keeps the reserved test set out, so it cannot be used for tuning.
    return UploadBatch.objects.filter(type=UploadBatch.Type.LISTINGS).exclude(
        dataset__in=RESERVED_DATASETS
    )


def _listing_batches(request: HttpRequest) -> Any:
    """Runnable batches the current user may see, with how many runs each already has."""
    return (
        scoped(_runnable_batches(), request.user)
        .select_related("district", "uploader")
        .annotate(run_count=Count("match_runs"))
        .order_by("-created_at", "-id")
    )


@require_capability(Capability.RUN_MATCHING)
def runs(request: HttpRequest) -> HttpResponse:
    """List the batches that can be run and the 50 most recent runs."""
    batches = _listing_batches(request)[:50]
    recent = (
        scoped(MatchRun, request.user)
        .select_related("district", "listing_batch", "created_by")
        .annotate(result_count=Count("results"))
        .order_by("-created_at", "-id")[:50]
    )
    return render(
        request,
        "matching/runs.html",
        {"batches": batches, "runs": recent, "is_admin": is_admin(request.user)},
    )


@require_capability(Capability.RUN_MATCHING)
@require_POST
def run_create(request: HttpRequest) -> HttpResponse:
    """Start a matching run from a form post. Admins get one run per district if the batch
    covers several districts. Officers always get one run, for their own district."""
    try:
        batch_id = int(request.POST.get("batch", ""))
    except ValueError:
        # A batch id that is not a number is treated as a page that does not exist.
        raise Http404 from None
    batch = get_scoped_or_404(_runnable_batches(), request, pk=batch_id)
    try:
        # A batch with no fixed district, run by an admin, spans districts: one run each.
        if batch.district is None and is_admin(request.user):
            created = run_matching_per_district(batch, actor=request.user)
        else:
            created = [run_matching(batch, actor=request.user)]
    except PermissionDenied:
        deny(request, "out_of_district", batch=batch.pk)
        raise  # unreachable; deny() raises
    except MatchingError as exc:
        # Show the reason on the runs page, instead of an error page.
        messages.error(
            request,
            _(
                "Matching could not start: %(reason)s. Check that a registry has been "
                "uploaded for this data set."
            )
            % {"reason": exc},
        )
        return redirect("runs")
    # One run goes straight to its summary. Several runs return to the list with a message.
    if len(created) == 1:
        return redirect("run_detail", pk=created[0].pk)
    messages.success(
        request, _("Created %(count)d matching runs, one per district.") % {"count": len(created)}
    )
    return redirect("runs")


@require_capability(Capability.RUN_MATCHING)
def run_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Show one run: how many listings fell into each band, and totals per status."""
    run = get_scoped_or_404(
        MatchRun.objects.select_related(
            "district", "listing_batch", "registry_batch", "created_by"
        ),
        request,
        pk=pk,
    )
    results = scoped(MatchResult, request.user).filter(run=run)
    # Count the results per band in one query. Maps band key to count.
    counts = {
        row["band"]: row["n"] for row in results.order_by().values("band").annotate(n=Count("id"))
    }
    labels = dict(MatchResult.Band.choices)
    status_labels = dict(MatchResult.Status.choices)
    # One row per band, in queue order, including bands with zero listings.
    bands = [
        {
            "key": band,
            "label": labels[band],
            "status": status_labels[engine.STATUS[band]],
            "status_key": engine.STATUS[band],
            "count": counts.get(band, 0),
        }
        for band in engine.BANDS
    ]
    # Add up the band counts for each status, for the summary at the top.
    status_totals = [
        {
            "key": key,
            "label": label,
            "count": sum(b["count"] for b in bands if b["status_key"] == key),
        }
        for key, label in MatchResult.Status.choices
    ]
    total = sum(b["count"] for b in bands)
    return render(
        request,
        "matching/run_detail.html",
        {
            "run": run,
            "bands": bands,
            "status_totals": status_totals,
            "total": total,
            "candidate_count": scoped(MatchCandidate, request.user).filter(run=run).count(),
        },
    )
