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
from accounts.permissions import authenticated_only, is_admin
from accounts.signals import ANONYMOUS_ACTOR


class LoginView(auth_views.LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        username = request.POST.get("username", "")
        # Count, password check and failure record happen inside one locked slot (D58).
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
        if form.data.get("username") and form.data.get("password"):
            throttle.record_ip_failure(self.request)
        return super().form_invalid(form)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["throttle"] = throttle.describe()
        context["idle_minutes"] = settings.SESSION_COOKIE_AGE // 60
        return context


class LogoutView(auth_views.LogoutView):
    """POST only (Django default). Adds a short notice on the login page."""

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        response = super().post(request, *args, **kwargs)
        messages.info(request, _("You have been signed out."))
        return response


@authenticated_only
def dashboard(request: HttpRequest) -> HttpResponse:
    """Placeholder landing page after sign-in. The officer queue arrives in M8."""
    user = request.user
    return render(
        request,
        "accounts/dashboard.html",
        {
            "is_admin": is_admin(user),
            "district": user.district,
        },
    )
