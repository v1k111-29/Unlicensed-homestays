"""Audit entries for authentication events (docs/security-and-privacy.md §3).

Hooked to Django's auth signals so every login path is covered, not only the login view.
No IP address, user agent or password is stored. A failed login stores the submitted username
(normalised) because the account throttle counts failures per username.
"""

from typing import Any

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

import audit
from accounts.throttle import username_key

ANONYMOUS_ACTOR = "anonymous"


@receiver(user_logged_in, dispatch_uid="audit_login")
def on_login(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
    audit.log(user, "login", "user", user.pk, {"role": user.role})


@receiver(user_logged_out, dispatch_uid="audit_logout")
def on_logout(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
    if user is not None:
        audit.log(user, "logout", "user", user.pk)


@receiver(user_login_failed, dispatch_uid="audit_login_failed")
def on_login_failed(sender: Any, credentials: dict, request: Any = None, **kwargs: Any) -> None:
    audit.log(
        ANONYMOUS_ACTOR,
        "login_failed",
        "username",
        username_key(credentials.get("username", "")),
        {"reason": "bad_credentials"},
    )
