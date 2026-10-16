"""Registry: the licence register that listings are matched against, and the uploads behind it.

`UploadBatch` records each accepted CSV file. `RegistryEntry` is one licensed stay in such a
file. Every entry belongs to exactly one batch, so an old batch stays intact after a new one is
uploaded.
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from accounts.models import District

# Data sets that no web flow may use: the synthetic test set is run once, at the end of tuning,
# by the eval harness only (AGENTS.md rule 9). Listings uploads never join it, officer runs
# never use it, and the tourist check never searches it. One constant for all of them.
RESERVED_DATASETS = frozenset({"synthetic-test"})


class UploadBatch(models.Model):
    """One accepted CSV file (registry or listings). Rejected files create no batch."""

    class Type(models.TextChoices):
        """Which kind of file the batch holds."""

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
    # SHA-256 of the file's bytes. Together with type and dataset it identifies a file.
    file_sha256 = models.CharField(max_length=64)
    row_count = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Admin label and database rules for upload batches."""

        verbose_name_plural = "upload batches"
        constraints = [
            # The same file may be loaded once per dataset and type, not twice.
            models.UniqueConstraint(
                fields=["type", "dataset", "file_sha256"], name="uniq_batch_file_per_dataset"
            ),
        ]

    def __str__(self) -> str:
        """Return a short label such as "registry batch 3 (synthetic-dev)"."""
        return f"{self.type} batch {self.pk} ({self.dataset or 'upload'})"


class RegistryEntry(models.Model):
    """One licensed stay in the registry: its licence number, name, place and validity dates."""

    class Category(models.TextChoices):
        """The kind of stay the licence covers."""

        HOMESTAY = "homestay", _("Homestay")
        COTTAGE = "cottage", _("Cottage")
        GUEST_HOUSE = "guest_house", _("Guest house")
        LODGE = "lodge", _("Lodge")

    class Status(models.TextChoices):
        """Whether the licence is currently in force."""

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
        """Admin label and database rules for registry entries."""

        verbose_name_plural = "registry entries"
        constraints = [
            # A licence number appears only once within one batch.
            models.UniqueConstraint(fields=["batch", "licence_no"], name="uniq_licence_per_batch"),
        ]
        # Database index on district and locality, the two fields that are searched together.
        indexes = [models.Index(fields=["district", "locality"])]

    def __str__(self) -> str:
        """Return the licence number followed by the name, for lists and admin pages."""
        return f"{self.licence_no} {self.name}"
