"""URL routes. Auth in M6; uploads and matching runs in M7; queue/cases in M8; tourist pages
in M9. Every view is guarded by a capability or is on the explicit public allowlist (a test walks
all routes). The Django admin site
is not installed, so `admin/` paths are ordinary guarded views."""

from django.urls import include, path

from config import health
from ingest import views as ingest_views
from matching import views as matching_views
from reviews import views as review_views
from tourist import views as tourist_views

urlpatterns = [
    # Public (allowlisted). Normally answered by config.health.HealthCheckMiddleware first (D77).
    path("livez", health.livez, name="livez"),
    path("healthz", health.healthz, name="healthz"),
    path("", include("accounts.urls")),
    path("check/", tourist_views.check, name="tourist_check"),  # public (allowlisted)
    path("officer/uploads/", ingest_views.upload_listings, name="upload_listings"),
    path(
        "officer/uploads/confirm/",
        ingest_views.upload_listings_confirm,
        name="upload_listings_confirm",
    ),
    path(
        "officer/uploads/cancel/",
        ingest_views.upload_listings_cancel,
        name="upload_listings_cancel",
    ),
    path("officer/runs/", matching_views.runs, name="runs"),
    path("officer/runs/start/", matching_views.run_create, name="run_create"),
    path("officer/runs/<int:pk>/", matching_views.run_detail, name="run_detail"),
    path("officer/queue/", review_views.queue, name="queue"),
    path("officer/cases/<int:pk>/", review_views.case_detail, name="case_detail"),
    path("officer/cases/<int:pk>/decide/", review_views.case_decide, name="case_decide"),
    path("officer/cases/<int:pk>/evidence/", review_views.case_evidence, name="case_evidence"),
    path("officer/evidence/<int:pk>/", review_views.evidence_detail, name="evidence_detail"),
    path("admin/registry/", ingest_views.upload_registry, name="upload_registry"),
    path(
        "admin/registry/confirm/",
        ingest_views.upload_registry_confirm,
        name="upload_registry_confirm",
    ),
    path(
        "admin/registry/cancel/",
        ingest_views.upload_registry_cancel,
        name="upload_registry_cancel",
    ),
]
