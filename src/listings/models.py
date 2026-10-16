"""Listings: the short descriptions of stays that officers check against the registry.

A listing is either uploaded by an officer from a CSV file or reported by a tourist. Matching
runs (in `matching`) read these rows; officer decisions (in `reviews`) point at them.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from accounts.models import District
from registry.models import UploadBatch


class Listing(models.Model):
    """A listing to check against the registry.

    `ref_url` is a stored string only. The app never fetches it (AGENTS.md rule 4), so no
    page on a booking platform is ever visited.
    """

    class Source(models.TextChoices):
        """Where the listing came from: an officer's CSV upload or a tourist report."""

        OFFICER_CSV = "officer_csv", _("Officer CSV upload")
        TOURIST_REPORT = "tourist_report", _("Tourist report")

    source = models.CharField(max_length=16, choices=Source.choices, default=Source.OFFICER_CSV)
    # Row id from the uploaded file, if any (synthetic `listing_id`, D35). Unique per batch.
    external_id = models.CharField(max_length=64, blank=True)
    platform = models.CharField(max_length=64)
    ref_url = models.CharField(max_length=500, blank=True)
    title = models.CharField(max_length=255)
    locality_text = models.CharField(max_length=255)
    pincode = models.CharField(max_length=6, blank=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    claimed_licence_no = models.CharField(max_length=64, blank=True)
    raw = models.JSONField(default=dict)
    batch = models.ForeignKey(
        UploadBatch, null=True, blank=True, on_delete=models.PROTECT, related_name="listings"
    )
    district = models.ForeignKey(District, on_delete=models.PROTECT, related_name="listings")

    class Meta:
        """Database rules for listings."""

        constraints = [
            # Two rows in the same upload may not share an external id. Rows with an empty
            # external id are left out of this rule.
            models.UniqueConstraint(
                fields=["batch", "external_id"],
                condition=~models.Q(external_id=""),
                name="uniq_external_id_per_batch",
            ),
        ]

    def __str__(self) -> str:
        """Return the listing title, which is what officers see in lists."""
        return self.title
