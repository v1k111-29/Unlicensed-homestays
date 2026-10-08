from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from listings.models import Listing
from matching.models import MatchRun
from registry.models import RegistryEntry


class Review(models.Model):
    """An officer decision. Only an officer may mark `suspected_unlicensed`, and a written
    reason is mandatory (AGENTS.md rule 1; enforced here by a DB constraint and in
    `reviews.services.decide`). Rows are only added: a later decision supersedes an earlier
    one, so the history of a case stays readable (M8, D59)."""

    class Decision(models.TextChoices):
        CONFIRM_MATCH = "confirm_match", _("Confirm match")
        REJECT_MATCH = "reject_match", _("Reject match")
        SUSPECTED_UNLICENSED = "suspected_unlicensed", _("Mark suspected unlicensed")
        DISMISS = "dismiss", _("Dismiss")

    listing = models.ForeignKey(Listing, on_delete=models.PROTECT, related_name="reviews")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    decision = models.CharField(max_length=32, choices=Decision.choices)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # M8: the run the officer was looking at, and the registry entry the decision is about
    # (confirm/reject). Both optional so earlier rows stay valid.
    run = models.ForeignKey(
        MatchRun, null=True, blank=True, on_delete=models.PROTECT, related_name="reviews"
    )
    registry_entry = models.ForeignKey(
        RegistryEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="reviews"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~Q(decision="suspected_unlicensed") | ~Q(reason=""),
                name="suspected_unlicensed_needs_reason",
            ),
        ]
        indexes = [models.Index(fields=["listing", "-id"], name="review_listing_latest")]

    def save(self, *args, **kwargs) -> None:
        if self.registry_entry_id is not None and (
            self.registry_entry.district_id != self.listing.district_id
        ):  # D51
            raise ValidationError("registry entry district differs from the listing district")
        if self.run_id is not None and self.run.district_id != self.listing.district_id:
            raise ValidationError("match run district differs from the listing district")
        super().save(*args, **kwargs)


class ConfirmedPair(models.Model):
    """Listing/registry pairs an officer confirmed; not re-flagged on later runs (O4)."""

    listing = models.ForeignKey(Listing, on_delete=models.CASCADE)
    registry_entry = models.ForeignKey(RegistryEntry, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["listing", "registry_entry"], name="uniq_pair"),
        ]

    def save(self, *args, **kwargs) -> None:
        if self.registry_entry.district_id != self.listing.district_id:  # D51
            raise ValidationError("registry entry district differs from the listing district")
        super().save(*args, **kwargs)


class EvidencePack(models.Model):
    listing = models.ForeignKey(Listing, on_delete=models.PROTECT, related_name="evidence")
    snapshot = models.JSONField()
    sha256 = models.CharField(max_length=64)
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
