"""Tourist check log (AGENTS.md rule 5, security-and-privacy.md §3).

One row per completed check: the result type and the time, nothing else. No IP address, no
query text, no user agent, no session or cookie id. A test pins the exact field list.
"""

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class TouristCheck(models.Model):
    class Result(models.TextChoices):
        FOUND = "found", _("Found in the registry")
        DIFFERS = "differs", _("Details differ")
        SEVERAL = "several", _("Several possible matches")
        NOT_FOUND = "not_found", _("Not found in the registry")

    result = models.CharField(max_length=16, choices=Result.choices)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "tourist_checks"

    def __str__(self) -> str:
        return f"{self.result} at {self.created_at:%Y-%m-%d %H:%M}"
