from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from accounts.models import District


class UploadBatch(models.Model):
    """One accepted CSV file (registry or listings). Rejected files create no batch."""

    class Type(models.TextChoices):
        REGISTRY = "registry", _("Registry")
        LISTINGS = "listings", _("Listings")

    type = models.CharField(max_length=16, choices=Type.choices)
    uploader = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    # Default district of a listings batch (D19); null for registry and multi-district batches.
    district = models.ForeignKey(District, null=True, blank=True, on_delete=models.PROTECT)
    # Free label, e.g. "synthetic-dev". Keeps the dev and test sets apart in one database (D40).
    dataset = models.CharField(max_length=32, blank=True, db_index=True)
    source_name = models.CharField(max_length=255, blank=True)
    file_sha256 = models.CharField(max_length=64)
    row_count = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "upload batches"
        constraints = [
            models.UniqueConstraint(
                fields=["type", "dataset", "file_sha256"], name="uniq_batch_file_per_dataset"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.type} batch {self.pk} ({self.dataset or 'upload'})"


class RegistryEntry(models.Model):
    class Category(models.TextChoices):
        HOMESTAY = "homestay", _("Homestay")
        COTTAGE = "cottage", _("Cottage")
        GUEST_HOUSE = "guest_house", _("Guest house")
        LODGE = "lodge", _("Lodge")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        EXPIRED = "expired", _("Expired")
        SUSPENDED = "suspended", _("Suspended")

    licence_no = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    address_en = models.CharField(max_length=500, blank=True)
    address_ta = models.CharField(max_length=500, blank=True)
    locality = models.CharField(max_length=255)
    pincode = models.CharField(max_length=6, blank=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    category = models.CharField(max_length=32, choices=Category.choices, blank=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    batch = models.ForeignKey(UploadBatch, on_delete=models.PROTECT, related_name="registry")
    district = models.ForeignKey(District, on_delete=models.PROTECT, related_name="registry")

    class Meta:
        verbose_name_plural = "registry entries"
        constraints = [
            models.UniqueConstraint(fields=["batch", "licence_no"], name="uniq_licence_per_batch"),
        ]
        indexes = [models.Index(fields=["district", "locality"])]

    def __str__(self) -> str:
        return f"{self.licence_no} {self.name}"
