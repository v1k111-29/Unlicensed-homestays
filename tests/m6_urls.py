"""Test-only views that use the M6 guards the way M7/M8 views must: every read and write of
district data goes through accounts.scoping, every view is guarded by a capability."""

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import include, path
from django.views import View

from accounts.permissions import Capability, CapabilityRequiredMixin, deny, require_capability
from accounts.scoping import can_act_in_district, get_scoped_or_404, scoped
from listings.models import Listing
from reviews.models import Review


@require_capability(Capability.DECIDE_CASES)
def listing_list(request: HttpRequest) -> HttpResponse:
    return JsonResponse({"ids": sorted(scoped(Listing, request.user).values_list("pk", flat=True))})


@require_capability(Capability.DECIDE_CASES)
def listing_detail(request: HttpRequest, pk: int) -> HttpResponse:
    listing = get_scoped_or_404(Listing, request, pk=pk)
    if request.method == "POST":
        listing.title = request.POST["title"]
        listing.save(update_fields=["title"])
        Review.objects.create(
            listing=listing, reviewer=request.user, decision="dismiss", reason="test"
        )
    return JsonResponse({"id": listing.pk, "title": listing.title})


@require_capability(Capability.UPLOAD_LISTINGS)
def upload_to_district(request: HttpRequest, district_id: int) -> HttpResponse:
    if not can_act_in_district(request.user, district_id):
        deny(request, "out_of_district", district_id=district_id)
    return HttpResponse("ok")


@require_capability(Capability.UPLOAD_REGISTRY)
def registry_upload(request: HttpRequest) -> HttpResponse:
    return HttpResponse("ok")


@require_capability(Capability.MANAGE_USERS)
def manage_users(request: HttpRequest) -> HttpResponse:
    return HttpResponse("ok")


@require_capability(Capability.RUN_MATCHING)
def run_matching(request: HttpRequest) -> HttpResponse:
    return HttpResponse("ok")


class AuditView(CapabilityRequiredMixin, View):
    required_capability = Capability.VIEW_AUDIT

    def get(self, request: HttpRequest) -> HttpResponse:
        return HttpResponse("ok")


urlpatterns = [
    path("", include("accounts.urls")),
    path("t/listings/", listing_list, name="t_listings"),
    path("t/listings/<int:pk>/", listing_detail, name="t_listing"),
    path("t/upload/<int:district_id>/", upload_to_district, name="t_upload"),
    path("t/registry/", registry_upload, name="t_registry"),
    path("t/users/", manage_users, name="t_users"),
    path("t/run/", run_matching, name="t_run"),
    path("t/audit/", AuditView.as_view(), name="t_audit"),
]
