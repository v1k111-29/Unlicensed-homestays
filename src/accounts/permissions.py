"""Roles and capabilities (docs/security-and-privacy.md §1).

The role matrix lives here and nowhere else. Views protect themselves with
`require_capability(...)` (function views) or `CapabilityRequiredMixin` (class views):
- anonymous users are redirected to the login page;
- signed-in users without the capability get 403, and the denial is audit-logged.

Capabilities come from `User.role` only. `is_superuser`/`is_staff` grant nothing here, and the
Django admin site is not installed, so there is no second path around this matrix.
"""

from collections.abc import Callable
from enum import StrEnum
from functools import wraps
from typing import Any

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse

import audit
from accounts.models import User


class Capability(StrEnum):
    TOURIST_CHECK = "tourist_check"
    UPLOAD_LISTINGS = "upload_listings"
    RUN_MATCHING = "run_matching"
    DECIDE_CASES = "decide_cases"
    UPLOAD_REGISTRY = "upload_registry"
    VIEW_AUDIT = "view_audit"
    MANAGE_USERS = "manage_users"


# Officer capabilities apply to the officer's own district only; scoping is enforced
# separately by accounts.scoping on every query (AGENTS.md rule 7).
ROLE_CAPABILITIES: dict[str, frozenset[Capability]] = {
    User.Role.OFFICER: frozenset(
        {
            Capability.TOURIST_CHECK,
            Capability.UPLOAD_LISTINGS,
            Capability.RUN_MATCHING,
            Capability.DECIDE_CASES,
        }
    ),
    User.Role.ADMIN: frozenset(Capability),
}

# What an anonymous visitor (tourist) may do.
ANONYMOUS_CAPABILITIES: frozenset[Capability] = frozenset({Capability.TOURIST_CHECK})


def is_admin(user: Any) -> bool:
    return bool(getattr(user, "is_authenticated", False) and user.is_active) and (
        user.role == User.Role.ADMIN
    )


def is_officer(user: Any) -> bool:
    """An active officer with a district. An officer without a district has no access."""
    return (
        bool(getattr(user, "is_authenticated", False) and user.is_active)
        and user.role == User.Role.OFFICER
        and user.district_id is not None
    )


def capabilities_for(user: Any) -> frozenset[Capability]:
    if not getattr(user, "is_authenticated", False):
        return ANONYMOUS_CAPABILITIES
    if is_admin(user) or is_officer(user):
        return ROLE_CAPABILITIES[user.role]
    return frozenset()  # inactive, unknown role, or officer without a district


def has_capability(user: Any, capability: Capability) -> bool:
    return capability in capabilities_for(user)


def deny(request: HttpRequest, reason: str, **meta: Any) -> None:
    """Audit-log a permission denial for a signed-in user, then raise 403.

    Only the request path is stored (no IP, no query string)."""
    audit.log(
        request.user,
        "permission_denied",
        "request",
        "",
        {"reason": reason, "path": request.path[:200], "method": request.method, **meta},
    )
    raise PermissionDenied(reason)


def _check(request: HttpRequest, capability: Capability) -> HttpResponse | None:
    """Return a login redirect for anonymous users, raise 403 if the capability is missing,
    or return None when access is allowed."""
    if has_capability(request.user, capability):
        return None
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    deny(request, "missing_capability", capability=str(capability))
    return None  # unreachable; deny() raises


def require_capability(capability: Capability) -> Callable:
    """Decorator for function views."""

    def decorator(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        @wraps(view)
        def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            response = _check(request, capability)
            if response is not None:
                return response
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


class CapabilityRequiredMixin:
    """Mixin for class-based views. Set `required_capability` on the view."""

    required_capability: Capability | None = None

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if self.required_capability is None:
            raise TypeError(f"{type(self).__name__} must set required_capability")
        response = _check(request, self.required_capability)
        if response is not None:
            return response
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]
