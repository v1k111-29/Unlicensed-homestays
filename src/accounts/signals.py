"""Audit entries for authentication events (docs/security-and-privacy.md §3).

Hooked to Django's auth signals so every login path is covered, not only the login view.
No IP address, user agent, password or typed username is stored: a failed login stores only an
HMAC of the normalised username (D46), which the account throttle counts.
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
    if user is not None:
        reason = getattr(request, "_logout_reason", "user")
        audit.log(user, "logout", "user", user.pk, {"reason": reason})


@receiver(user_login_failed, dispatch_uid="audit_login_failed")
def on_login_failed(sender: Any, credentials: dict, request: Any = None, **kwargs: Any) -> None:
    audit.log(
        ANONYMOUS_ACTOR,
        "login_failed",
        "username_hmac",
        username_digest(credentials.get("username", "")),
        {"reason": "bad_credentials"},
    )
