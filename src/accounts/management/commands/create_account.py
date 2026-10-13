"""Create an admin or officer account (synthetic demo accounts only; no real people).

    python src/manage.py create_account <username> --role officer --district Nilgiris
    python src/manage.py create_account <username> --role admin

The password is read from the environment variable named by --password-env, or prompted for.
It is never accepted on the command line (shell history). Audit-logged as a user change.
The rules (username, role/district, password validators) live in `accounts.services` and are
shared with the admin account screen (D92).
"""

import getpass
import os

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from accounts.services import AccountError, check_account_fields, create_account

ACTOR = "system:create_account"


class Command(BaseCommand):
    help = "Create an admin or officer account. Officers need a district."

    def add_arguments(self, parser) -> None:
        parser.add_argument("username")
        parser.add_argument("--role", choices=[r.value for r in User.Role], required=True)
        parser.add_argument("--district", help="District name in English (officers only)")
        parser.add_argument("--password-env", help="Read the password from this env variable")

    def handle(self, *args, **options) -> None:
        username: str = options["username"]
        role: str = options["role"]
        try:
            # Check the fields before asking for a password.
            check_account_fields(username, role, options["district"])
        except AccountError as exc:
            raise CommandError(f"{exc.field or 'account'}: {exc.message}") from None

        if options["password_env"]:
            password = os.environ.get(options["password_env"], "")
            if not password:
                raise CommandError(f"environment variable {options['password_env']} is empty")
        else:
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Password (again): "):
                raise CommandError("passwords do not match")

        try:
            create_account(
                ACTOR,
                username,
                role,
                options["district"],
                password,
                action="user_created",
                via="command",
            )
        except AccountError as exc:
            raise CommandError(f"{exc.field or 'account'}: {exc.message}") from None
        self.stdout.write(f"created {role} '{username.strip()}'")
