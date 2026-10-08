"""Create an admin or officer account (synthetic demo accounts only; no real people).

    python src/manage.py create_account <username> --role officer --district Nilgiris
    python src/manage.py create_account <username> --role admin

The password is read from the environment variable named by --password-env, or prompted for.
It is never accepted on the command line (shell history). Audit-logged as a user change.
"""

import getpass
import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

import audit
from accounts.models import District, User

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
        if User.objects.filter(username__iexact=username).exists():
            raise CommandError(f"user '{username}' already exists")

        district = None
        if role == User.Role.OFFICER:
            if not options["district"]:
                raise CommandError("--district is required for officers")
            try:
                district = District.objects.get(name_en__iexact=options["district"])
            except District.DoesNotExist:
                raise CommandError(f"unknown district '{options['district']}'") from None
        elif options["district"]:
            raise CommandError("admins are not tied to a district; omit --district")

        if options["password_env"]:
            password = os.environ.get(options["password_env"], "")
            if not password:
                raise CommandError(f"environment variable {options['password_env']} is empty")
        else:
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Password (again): "):
                raise CommandError("passwords do not match")

        user = User(username=username, role=role, district=district)
        try:
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from None
        user.set_password(password)

        with transaction.atomic():
            user.save()
            audit.log(
                ACTOR,
                "user_created",
                "user",
                user.pk,
                {"role": role, "district": district.name_en if district else None},
            )
        self.stdout.write(f"created {role} '{username}'")
