"""Roles and capabilities (docs/security-and-privacy.md §1).

The role matrix lives here and nowhere else. Views protect themselves with
`require_capability(...)` (function views) or `CapabilityRequiredMixin` (class views):
- anonymous users are redirected to the login page;
- signed-in users without the capability get 403, and the denial is audit-logged.

Capabilities come from `User.role` only. `is_superuser`/`is_staff` grant nothing here, and the
Django admin site is not installed, so there is no second path around this matrix.

Used by: protected views (through the decorator or mixin below) and the audit helpers.
Key idea: one table maps each role to its capabilities, so a permission change is an edit in
one place and a test can check the whole matrix at once.
"""

from collections.abc import Callable
from enum import StrEnum
from functools import wraps
from typing import Any

from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse

import audit
from accounts.models import User


class Capability(StrEnum):
    """One named action a user may be allowed to perform. The string values are written into
    audit meta on a denial, so changing them would change the recorded history."""

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
    """An active, signed-in administrator. Administrators see every district."""
    # The active check comes first so a disabled admin account loses access at once.
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
    """The full set of capabilities this user holds. Anything not recognised gets an empty set,
    so the default is to deny."""
    if not getattr(user, "is_authenticated", False):
        return ANONYMOUS_CAPABILITIES
    if is_admin(user) or is_officer(user):
        return ROLE_CAPABILITIES[user.role]
    return frozenset()  # inactive, unknown role, or officer without a district


def has_capability(user: Any, capability: Capability) -> bool:
    """True if `user` holds `capability`. Use this for checks inside a view body."""
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
    # Anonymous visitors are sent to log in rather than shown 403, so they can sign in and
    # come back. Only a signed-in user who lacks the capability is audited and refused.
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    deny(request, "missing_capability", capability=str(capability))
    return None  # unreachable; deny() raises


def require_capability(capability: Capability) -> Callable:
    """Decorator for function views. Wraps the view so the capability is checked before the
    view body runs. `access_guard` is a marker the URL-guard test reads to confirm the view
    is protected."""

    def decorator(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        # @wraps keeps the original view's name and docstring on the wrapper.
        @wraps(view)
        def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            response = _check(request, capability)
            if response is not None:
                return response
            return view(request, *args, **kwargs)

        wrapped.access_guard = f"capability:{capability}"  # type: ignore[attr-defined]
        return wrapped

    return decorator


def authenticated_only(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """For pages any signed-in user may see (no district data). Anonymous -> login redirect.
    Marked so the URL-guard test can tell it is protected."""
    wrapped = login_required(view)
    wrapped.access_guard = "authenticated"  # type: ignore[attr-defined]
    return wrapped


class CapabilityRequiredMixin:
    """Mixin for class-based views. Set `required_capability` on the view. The check runs in
    `dispatch`, before any GET or POST handler, so no handler can run without it."""

    required_capability: Capability | None = None

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Check the capability, then hand the request to the normal Django dispatch."""
        # Failing loudly here stops a developer from forgetting to set the capability: the
        # view would otherwise be open to everyone.
        if self.required_capability is None:
            raise TypeError(f"{type(self).__name__} must set required_capability")
        response = _check(request, self.required_capability)
        if response is not None:
            return response
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]
