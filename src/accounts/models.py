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
        return self.name_en


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", _("Admin")
        OFFICER = "officer", _("Officer")

    role = models.CharField(max_length=16, choices=Role.choices, default=Role.OFFICER)
    district = models.ForeignKey(
        District, null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(role="admin") | Q(district__isnull=False),
                name="officer_has_district",
            ),
            # Usernames differing only in case would share one throttle key (D46).
            models.UniqueConstraint(Lower("username"), name="uniq_username_ci"),
        ]
