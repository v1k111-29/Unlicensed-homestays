"""Audit entries for authentication events (docs/security-and-privacy.md §3).

Hooked to Django's auth signals so every login path is covered, not only the login view.
No IP address, user agent, password or typed username is stored: a failed login stores only an
HMAC of the normalised username (D58), which the account throttle counts.
"""

import time
from typing import Any

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

import audit
from accounts.throttle import username_digest

ANONYMOUS_ACTOR = "system:anonymous"
SESSION_LOGIN_AT = "login_at"  # read by accounts.middleware (absolute session lifetime)


@receiver(user_logged_in, dispatch_uid="audit_login")
def on_login(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
    """Record the login time in the session (for the absolute lifetime) and audit the login."""
    # The start time lives in the session so the middleware can read it on later requests.
    if request is not None and hasattr(request, "session"):
        request.session[SESSION_LOGIN_AT] = int(time.time())
    audit.log(
        user,
        "login",
        "user",
        user.pk,
        {"role": user.role, "username_hmac": username_digest(user.get_username())},
    )


@receiver(user_logged_out, dispatch_uid="audit_logout")
def on_logout(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
    """Audit a logout. The reason is "session_expired" when the middleware ended the session,
    otherwise "user"."""
    # Logouts without a user (for example, an already-expired session) have no actor to record.
    if user is not None:
        reason = getattr(request, "_logout_reason", "user")
        audit.log(user, "logout", "user", user.pk, {"reason": reason})


@receiver(user_login_failed, dispatch_uid="audit_login_failed")
def on_login_failed(sender: Any, credentials: dict, request: Any = None, **kwargs: Any) -> None:
    """Audit a failed password check. Only the HMAC of the username is stored, so the throttle
    can count failures without the audit log holding the typed name."""
    # The actor is the anonymous placeholder because no account was signed in.
    audit.log(
        ANONYMOUS_ACTOR,
        "login_failed",
        "username_hmac",
        username_digest(credentials.get("username", "")),
        {"reason": "bad_credentials"},
    )
