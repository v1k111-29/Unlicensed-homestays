from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _


class District(models.Model):
    """A Tamil Nadu district. Officers are scoped to exactly one (AGENTS.md rule 7)."""

    name_en = models.CharField(max_length=100, unique=True)
    name_ta = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["name_en"]

    def __str__(self) -> str:
        """The English name, used in admin screens and messages."""
        return self.name_en


class User(AbstractUser):
    """A signed-in account. The role decides what the user may do (see accounts.permissions),
    and an officer's district decides which records they may see (see accounts.scoping)."""

    class Role(models.TextChoices):
        """The two roles. The stored values are used in the role matrix and the database."""

        ADMIN = "admin", _("Admin")
        OFFICER = "officer", _("Officer")

    role = models.CharField(max_length=16, choices=Role.choices, default=Role.OFFICER)
    district = models.ForeignKey(
        District, null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )

    class Meta:
        constraints = [
            # The database itself refuses an officer without a district, even if the code
            # forgets to check. Administrators have no district.
            models.CheckConstraint(
                condition=Q(role="admin") | Q(district__isnull=False),
                name="officer_has_district",
            ),
            # Usernames differing only in case would share one throttle key (D58).
            models.UniqueConstraint(Lower("username"), name="uniq_username_ci"),
        ]
