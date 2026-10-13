"""Account management screens (admin only, D92): list, create, disable/enable, reset password.

Rules live in `accounts.services` (shared with the `create_account` command). Every change is
POST + CSRF and writes one audit entry there. A generated password is put into the response
of that POST only: it is not stored in the session, a message, a URL, a log or the audit meta,
and the response is marked `no-store`. There is no hard delete (audit rows name actors by text).
Account management is admin-wide by design; the list still goes through `accounts.scoping`.
"""

from __future__ import annotations

from typing import Any

from django import forms
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.db.models import Case, IntegerField, Value, When
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.cache import add_never_cache_headers
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts import services
from accounts.models import District, User
from accounts.permissions import Capability, require_capability
from accounts.scoping import get_scoped_or_404, scoped


class AccountForm(forms.Form):
    # Length and character rules are checked by accounts.services (one place, D92).
    username = forms.CharField(
        label=gettext_lazy("Username"),
        strip=True,
        error_messages={"required": gettext_lazy("Enter a username.")},
    )
    role = forms.ChoiceField(
        label=gettext_lazy("Role"),
        choices=User.Role.choices,
        error_messages={"required": gettext_lazy("Choose a role.")},
    )
    district = forms.ModelChoiceField(
        label=gettext_lazy("District"),
        queryset=District.objects.order_by("name_en"),
        required=False,
        empty_label=gettext_lazy("No district (administrators)"),
    )


def _no_store(response: HttpResponse) -> HttpResponse:
    add_never_cache_headers(response)  # includes Cache-Control: no-store
    return response


@require_capability(Capability.MANAGE_USERS)
@require_GET
def account_list(request: HttpRequest) -> HttpResponse:
    accounts = (
        scoped(User, request.user)  # admin: every account (D92)
        .select_related("district")
        .annotate(
            role_order=Case(
                When(role=User.Role.ADMIN, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("-is_active", "role_order", "username")
    )
    return render(request, "accounts/manage_list.html", {"accounts": accounts})


@require_capability(Capability.MANAGE_USERS)
@require_http_methods(["GET", "POST"])
def account_create(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        form = AccountForm(initial={"role": User.Role.OFFICER})
        return render(request, "accounts/manage_create.html", {"form": form})
    form = AccountForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        password = services.generate_password()
        try:
            user = services.create_account(
                request.user, data["username"], data["role"], data["district"], password
            )
        except services.AccountError as exc:
            form.add_error(exc.field if exc.field in form.fields else None, exc.message)
        else:
            return _no_store(
                render(
                    request,
                    "accounts/manage_password.html",
                    {"account": user, "password": password, "created": True},
                )
            )
    return render(request, "accounts/manage_create.html", {"form": form}, status=400)


def _set_active(request: HttpRequest, pk: int, active: bool) -> HttpResponse:
    target = get_scoped_or_404(User, request, pk=pk)
    try:
        services.set_active(request.user, target.pk, active)
    except services.AccountError as exc:
        messages.error(request, exc.message)
    else:
        if active:
            messages.success(request, _("Account %(name)s enabled.") % {"name": target.username})
        else:
            messages.success(
                request,
                _("Account %(name)s disabled. It can no longer sign in.")
                % {"name": target.username},
            )
    return redirect("account_list")


@require_capability(Capability.MANAGE_USERS)
@require_POST
def account_disable(request: HttpRequest, pk: int) -> HttpResponse:
    return _set_active(request, pk, active=False)


@require_capability(Capability.MANAGE_USERS)
@require_POST
def account_enable(request: HttpRequest, pk: int) -> HttpResponse:
    return _set_active(request, pk, active=True)


@require_capability(Capability.MANAGE_USERS)
@require_POST
def account_reset_password(request: HttpRequest, pk: int) -> HttpResponse:
    target = get_scoped_or_404(User, request, pk=pk)
    user, password = services.reset_password(request.user, target.pk)
    if user.pk == request.user.pk:
        update_session_auth_hash(request, user)  # keep the admin's own session
    context: dict[str, Any] = {"account": user, "password": password, "created": False}
    return _no_store(render(request, "accounts/manage_password.html", context))
