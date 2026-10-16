"""Account rules shared by the `create_account` command and the admin account screens (D92).

One place for: username rules, role/district rules, password validation, the generated
one-time password, and the guards on disabling accounts. Every change writes one audit entry
via `audit.log`; passwords never reach audit meta, logs, sessions or URLs.

Scope: account management is admin-wide by design (D92). Officers never reach these functions
through the web (capability MANAGE_USERS); the command runs as `system:create_account`.
"""

from __future__ import annotations

import secrets
import string
from typing import Any

from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import ASCIIUsernameValidator
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext_lazy as _

import audit
from accounts.models import District, User
from accounts.throttle import USERNAME_KEY_LEN

# Usernames: ASCII letters, digits and @ . + - _ only, at most 64 characters, unique ignoring
# case (DB constraint `uniq_username_ci`). ASCII avoids look-alike letters; 64 is the length
# the login throttle keys on (D58/D65), so two names never share a throttle key by truncation.
USERNAME_MAX = USERNAME_KEY_LEN
_username_validator = ASCIIUsernameValidator()

# One-time passwords: 4 groups of 5 characters from 57 unambiguous letters and digits
# (about 117 bits). Shown once on the confirmation page; never stored in clear.
_AMBIGUOUS = frozenset("IOl01")
_PASSWORD_ALPHABET = "".join(c for c in string.ascii_letters + string.digits if c not in _AMBIGUOUS)
_PASSWORD_GROUPS = 4
_PASSWORD_GROUP_LEN = 5


class AccountError(Exception):
    """A rule was broken. `field` names the form field it belongs to ("" for the whole form).
    `message` is translatable (lazy); the command prints it in English."""

    def __init__(self, field: str, message: Any) -> None:
        super().__init__(str(message))
        self.field = field
        self.message = message


def generate_password() -> str:
    """Build a one-time password such as "ABCDE-FGHJK-...". Uses `secrets`, not `random`, so the
    output cannot be predicted from earlier output."""
    groups = (
        "".join(secrets.choice(_PASSWORD_ALPHABET) for _n in range(_PASSWORD_GROUP_LEN))
        for _g in range(_PASSWORD_GROUPS)
    )
    return "-".join(groups)


def _resolve_district(district: District | str | int | None) -> District | None:
    """Turn a District, its id, or its English name into a District. Empty input gives None."""
    if district is None or district == "":
        return None
    if isinstance(district, District):
        return district
    try:
        if isinstance(district, int):
            return District.objects.get(pk=district)
        return District.objects.get(name_en__iexact=district.strip())
    except District.DoesNotExist:
        raise AccountError("district", _("Unknown district.")) from None


def check_account_fields(
    username: str, role: str, district: District | str | int | None
) -> tuple[str, str, District | None]:
    """Validate the fields of a new account without saving. Returns cleaned values.

    The checks run in a fixed order and stop at the first failure, so each error names one
    field. The username is checked for existence after its format, so a malformed name
    never reaches the database."""
    username = (username or "").strip()
    if not username:
        raise AccountError("username", _("Enter a username."))
    if len(username) > USERNAME_MAX:
        raise AccountError(
            "username",
            _("Use at most %(max)d characters.") % {"max": USERNAME_MAX},
        )
    try:
        _username_validator(username)
    except ValidationError:
        raise AccountError(
            "username",
            _("Use only English letters, digits and the characters @ . + - _"),
        ) from None
    if User.objects.filter(username__iexact=username).exists():
        raise AccountError("username", _("An account with this username already exists."))

    if role not in User.Role.values:
        raise AccountError("role", _("Choose a role."))
    resolved = _resolve_district(district)
    if role == User.Role.OFFICER and resolved is None:
        raise AccountError("district", _("Officers need a district."))
    if role == User.Role.ADMIN and resolved is not None:
        raise AccountError("district", _("Administrators are not tied to a district."))
    return username, role, resolved


def create_account(
    actor: Any,
    username: str,
    role: str,
    district: District | str | int | None,
    password: str,
    *,
    action: str = "account.create",
    via: str = "web",
) -> User:
    """Create an account after checking every rule. The password is validated with the
    configured validators and stored hashed only; it is not written to the audit meta."""
    username, role, resolved = check_account_fields(username, role, district)
    user = User(username=username, role=role, district=resolved)
    # Password rules are checked against the unsaved user so validators can compare the password
    # with the username and other fields.
    try:
        validate_password(password, user)
    except ValidationError as exc:
        raise AccountError("password", "; ".join(exc.messages)) from None
    user.set_password(password)
    # The save and its audit entry share one transaction: either both are stored or neither is.
    try:
        with transaction.atomic():
            user.save()
            audit.log(
                actor,
                action,
                "user",
                user.pk,
                {
                    "username": username,
                    "role": role,
                    "district": resolved.name_en if resolved else None,
                    "via": via,
                },
            )
    except IntegrityError:  # a concurrent create with the same name (case-insensitive)
        raise AccountError("username", _("An account with this username already exists.")) from None
    return user


def set_active(actor: User, target_pk: int, active: bool) -> User:
    """Disable or enable an account. Refuses to disable yourself or the last active admin.
    Rows are locked so two admins cannot disable each other at the same time."""
    with transaction.atomic():
        # select_for_update locks the target row until the transaction ends, so the admin count
        # below cannot change under us.
        target = User.objects.select_for_update().get(pk=target_pk)
        if not active:
            # Both guards stop an admin locking everyone out of the system.
            if target.pk == actor.pk:
                raise AccountError("", _("You cannot disable your own account."))
            if target.role == User.Role.ADMIN and target.is_active:
                others = (
                    User.objects.select_for_update()
                    .filter(role=User.Role.ADMIN, is_active=True)
                    .exclude(pk=target.pk)
                )
                if not list(others):
                    raise AccountError("", _("The last active administrator cannot be disabled."))
        if target.is_active == active:
            return target  # nothing to change, nothing to audit
        target.is_active = active
        target.save(update_fields=["is_active"])
        audit.log(
            actor,
            "account.enable" if active else "account.disable",
            "user",
            target.pk,
            {"username": target.get_username(), "role": target.role},
        )
    return target


def reset_password(actor: User, target_pk: int) -> tuple[User, str]:
    """Give an account a new generated one-time password. Returns (user, password); the
    caller shows the password once and keeps it nowhere. Changing the password ends the
    account's other sessions (Django checks the password hash on each request)."""
    with transaction.atomic():
        # Lock the row so a concurrent password change cannot interleave with this one.
        target = User.objects.select_for_update().get(pk=target_pk)
        password = generate_password()
        validate_password(password, target)
        target.set_password(password)
        target.save(update_fields=["password"])
        audit.log(
            actor,
            "account.reset_password",
            "user",
            target.pk,
            {"username": target.get_username()},
        )
    return target, password
