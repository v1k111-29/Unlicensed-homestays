"""District scoping: the single server-side filter for every officer query (AGENTS.md rule 7).

Every view or service that reads or changes district data starts from `scoped(...)` or
`get_scoped_or_404(...)`. Never filter by district ad hoc in a view, and never rely on the UI.

Rules:
- admin: all districts (D21);
- officer with a district: rows of that district only;
- anyone else (anonymous, inactive, officer without district, unknown role): no rows.
- A model that is not listed in DISTRICT_PATHS raises ImproperlyConfigured (fail closed),
  so a new district-bearing model cannot be queried until its path is declared here.
"""

from typing import Any, TypeVar

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Model, QuerySet
from django.http import Http404, HttpRequest

import audit
from accounts.models import District
from accounts.permissions import is_admin, is_officer

M = TypeVar("M", bound=Model)

# "app_label.ModelName" -> ORM lookup path from that model to accounts.District.
# Paths follow forward foreign keys only (no reverse relations, so no duplicates).
# UploadBatch: registry batches have no district and are admin-only; listings batches are
# scoped by their district (D64).
DISTRICT_PATHS: dict[str, str] = {
    "accounts.District": "pk",
    "accounts.User": "district",
    "registry.UploadBatch": "district",
    "registry.RegistryEntry": "district",
    "listings.Listing": "district",
    "matching.MatchCandidate": "listing__district",
    "matching.MatchResult": "listing__district",
    "matching.GroundTruth": "listing__district",
    "matching.MatchRun": "district",
    "reviews.Review": "listing__district",
    "reviews.ConfirmedPair": "listing__district",
    "reviews.EvidencePack": "listing__district",
}


def _key(model: type[Model]) -> str:
    return f"{model._meta.app_label}.{model.__name__}"


def district_path(model: type[Model]) -> str:
    try:
        return DISTRICT_PATHS[_key(model)]
    except KeyError:
        raise ImproperlyConfigured(
            f"{_key(model)} has no district path in accounts.scoping.DISTRICT_PATHS"
        ) from None


def scoped(source: type[M] | QuerySet[M], user: Any) -> QuerySet[M]:
    """Return `source` (a model class or queryset) limited to what `user` may see."""
    qs = source if isinstance(source, QuerySet) else source._default_manager.all()
    path = district_path(qs.model)  # check first: unknown models fail even for admins
    if is_admin(user):
        return qs
    if not is_officer(user):
        return qs.none()
    return qs.filter(**{path: user.district_id})


def get_scoped_or_404(source: type[M] | QuerySet[M], request: HttpRequest, **lookup: Any) -> M:
    """Fetch one object inside the user's scope, else 404.

    An object that exists but lies outside the user's district also gives 404 (its existence is
    not revealed), and the attempt is audit-logged as a permission denial."""
    qs = scoped(source, request.user)
    try:
        return qs.get(**lookup)
    except qs.model.DoesNotExist:
        base = source if isinstance(source, QuerySet) else source._default_manager.all()
        if request.user.is_authenticated and base.filter(**lookup).exists():
            audit.log(
                request.user,
                "permission_denied",
                _key(qs.model),
                lookup.get("pk", lookup.get("id", "")),
                {"reason": "out_of_district", "path": request.path[:200]},
            )
        raise Http404 from None


def can_act_in_district(user: Any, district: District | int | None) -> bool:
    """For writes that name a district (e.g. an upload's target district, D30)."""
    if district is None:
        return False
    district_id = district if isinstance(district, int) else district.pk
    return is_admin(user) or (is_officer(user) and user.district_id == district_id)
