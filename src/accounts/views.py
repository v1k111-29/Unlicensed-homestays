"""Login, logout and a minimal signed-in landing page. Business rules live in
accounts.permissions, accounts.scoping and accounts.throttle, not here."""

from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext as _

import audit
from accounts import throttle
from accounts.models import User
from accounts.permissions import Capability, authenticated_only, has_capability, is_admin
from accounts.signals import ANONYMOUS_ACTOR


class LoginView(auth_views.LoginView):
    """The sign-in page. Adds the login throttle in front of Django's own password check."""

    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Handle a sign-in attempt, refusing it first if the throttle says the account or
        address has too many recent failures."""
        username = request.POST.get("username", "")
        # Count, password check and failure record happen inside one locked slot (D58), so two
        # parallel attempts cannot both pass a count that was taken before either failed.
        with throttle.login_slot(request, username):
            scope = throttle.blocked_scope(request, username)
            if scope is None:
                return super().post(request, *args, **kwargs)
            audit.log(
                ANONYMOUS_ACTOR,
                "login_throttled",
                "username_hmac",
                throttle.username_digest(username),
                {"scope": scope},
            )
        # The password is not checked while throttled.
        context = self.get_context_data(
            form=self.get_form_class()(request, initial={"username": username}),
            throttled=True,
        )
        return self.render_to_response(context, status=429)

    def form_invalid(self, form: Any) -> HttpResponse:
        """Count a failed attempt against the address, but only when both fields were filled in.
        Blank submissions are not counted as guesses."""
        if form.data.get("username") and form.data.get("password"):
            throttle.record_ip_failure(self.request)
        return super().form_invalid(form)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Add the throttle limits, idle timeout and demo accounts to the login page."""
        context = super().get_context_data(**kwargs)
        context["throttle"] = throttle.describe()
        context["idle_minutes"] = settings.SESSION_COOKIE_AGE // 60
        context["demo_accounts"] = demo_accounts()
        return context


def demo_accounts() -> list[dict[str, Any]]:
    """Demo accounts to show on the login page (D96): only those configured in the
    environment that exist and are active, with the officer's district."""
    labels = {"officer": _("Officer"), "admin": _("Administrator")}
    # Only configured, active accounts are listed, so a disabled demo account is never shown.
    shown = []
    for item in settings.DEMO_LOGIN_ACCOUNTS:
        user = (
            User.objects.filter(username=item["username"], is_active=True)
            .select_related("district")
            .first()
        )
        if user is None:
            continue
        shown.append(
            {
                "role": labels[item["role"]],
                "district": user.district,
                "username": item["username"],
                "password": item["password"],
            }
        )
    return shown


class LogoutView(auth_views.LogoutView):
    """POST only (Django default). Adds a short notice on the login page."""

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Sign out, then queue the notice so it shows on the next page."""
        response = super().post(request, *args, **kwargs)
        messages.info(request, _("You have been signed out."))
        return response


@authenticated_only
def dashboard(request: HttpRequest) -> HttpResponse:
    """Landing page after sign-in: real counts for the user's scope (M8). Counts go through
    accounts.scoping inside reviews.services, so an officer only sees their own district."""
    from reviews.services import dashboard_counts  # lazy: accounts must not import reviews early

    user = request.user
    allowed = has_capability(user, Capability.DECIDE_CASES)
    return render(
        request,
        "accounts/dashboard.html",
        {
            "is_admin": is_admin(user),
            "district": user.district,
            "counts": dashboard_counts(user) if allowed else None,
        },
    )
