"""Absolute session lifetime (D59): a signed-in session ends SESSION_ABSOLUTE_SECONDS after
login even if it stays active. The idle timeout is Django's SESSION_COOKIE_AGE."""

import time
from collections.abc import Callable

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse
from django.utils.translation import gettext as _

from accounts.signals import SESSION_LOGIN_AT


class AbsoluteSessionLifetimeMiddleware:
    """Ends a signed-in session once its absolute lifetime has passed, however active it is.
    Idle timeouts alone would let an active session run forever, so this caps the total time."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """Store the next handler in the middleware chain."""
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Check the session age on each request for a signed-in user, then pass it on."""
        if request.user.is_authenticated:
            now = int(time.time())
            started = request.session.get(SESSION_LOGIN_AT)
            if started is None:
                # A session created before this rule has no start time. Give it one now, so it
                # gets the full lifetime from this point rather than being ended at once.
                request.session[SESSION_LOGIN_AT] = now
            elif now - int(started) > settings.SESSION_ABSOLUTE_SECONDS:
                request._logout_reason = "session_expired"
                logout(request)
                messages.info(request, _("Your session has expired. Please sign in again."))
                return redirect_to_login(request.get_full_path())
        return self.get_response(request)
