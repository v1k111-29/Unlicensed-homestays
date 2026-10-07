from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from listings.models import Listing
from registry.models import RegistryEntry, UploadBatch


class MatchRun(models.Model):
    """One matching run. `params_version` makes results reproducible (AGENTS.md §8).
    `thresholds` holds the full parameter snapshot of that version (M4)."""

    params_version = models.CharField(max_length=32)
    thresholds = models.JSONField(default=dict)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # What was matched against what, and the date licence validity was judged on (D54).
    listing_batch = models.ForeignKey(
        UploadBatch,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="match_runs",
    )
    registry_batch = models.ForeignKey(
        UploadBatch,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="registry_match_runs",
    )
    as_of = models.DateField(null=True, blank=True)


class MatchCandidate(models.Model):
    run = models.ForeignKey(MatchRun, on_delete=models.CASCADE, related_name="candidates")
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="candidates")
    registry_entry = models.ForeignKey(RegistryEntry, on_delete=models.PROTECT)
    score = models.FloatField()
    features = models.JSONField(default=dict)
    rank = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "listing", "registry_entry"], name="uniq_candidate_per_run"
            ),
        ]


class MatchResult(models.Model):
    """Prioritises a listing for human review. Never a finding (AGENTS.md rule 1)."""

    class Status(models.TextChoices):
        MATCHED = "matched", _("Matched")
        NEEDS_REVIEW = "needs_review", _("Needs review")
        NO_MATCH = "no_match", _("No match")

    class Band(models.TextChoices):
        """Status bands of data-and-matching.md §7 (keys from ``matching.engine``). Labels
        describe what the officer should do next; they never judge the stay."""

        REVIEW_LICENCE = "review_licence", _("Needs review - high priority (licence details)")
        NO_CANDIDATE = "no_candidate", _("No match - needs review")
        REVIEW_SCORE = "review_score", _("Needs review")
        MATCHED_SCORE = "matched_score", _("Matched (optional review)")
        MATCHED_LICENCE = "matched_licence", _("Matched (licence and details agree)")
        MATCHED_CONFIRMED = "matched_confirmed", _("Matched (confirmed by an officer)")

    run = models.ForeignKey(MatchRun, on_delete=models.CASCADE, related_name="results")
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="results")
    status = models.CharField(max_length=16, choices=Status.choices)
    band = models.CharField(max_length=32, choices=Band.choices, blank=True)
    # Reason codes from the engine (e.g. "licence_not_valid"); rendered via gettext later.
    reasons = models.JSONField(default=list)
    top_registry_entry = models.ForeignKey(
        RegistryEntry, null=True, blank=True, on_delete=models.PROTECT
    )
    score = models.FloatField(null=True, blank=True)
    priority = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "listing"], name="uniq_result_per_run"),
        ]


class GroundTruth(models.Model):
    """Synthetic evaluation labels (M1 `ground_truth.csv`). Used by the eval harness only;
    the matcher must never read this table (D35)."""

    class Type(models.TextChoices):
        CLEAN = "clean", "clean"
        NOISY = "noisy", "noisy"
        WRONG_OR_EXPIRED = "wrong_or_expired", "wrong_or_expired"
        NO_COUNTERPART = "no_counterpart", "no_counterpart"
        HARD_NEGATIVE = "hard_negative", "hard_negative"

    listing = models.OneToOneField(Listing, on_delete=models.CASCADE, related_name="ground_truth")
    true_registry_entry = models.ForeignKey(
        RegistryEntry, null=True, blank=True, on_delete=models.PROTECT
    )
    type = models.CharField(max_length=32, choices=Type.choices)
    noise = models.CharField(max_length=100, blank=True)
