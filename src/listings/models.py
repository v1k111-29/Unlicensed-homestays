from django.db import models
from django.utils.translation import gettext_lazy as _

from accounts.models import District
from registry.models import UploadBatch


class Listing(models.Model):
    """A listing to check against the registry. `ref_url` is a stored string only; it is never
    fetched (AGENTS.md rule 4)."""

    class Source(models.TextChoices):
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
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "external_id"],
                condition=~models.Q(external_id=""),
                name="uniq_external_id_per_batch",
            ),
        ]

    def __str__(self) -> str:
        return self.title
