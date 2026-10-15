"""Database tables for matching: runs, candidates, results and synthetic ground truth.

What this file is for: it stores what a matching run produced. One ``MatchRun`` is one
pass over one district. Each run has many ``MatchCandidate`` rows (possible registry
matches) and one ``MatchResult`` per listing (its band and reasons).

Who uses it: ``services.run_matching`` writes these tables, and ``views`` and the
templates read them. ``GroundTruth`` is only read by the evaluation harness.

Django models only. The matching rules themselves live in ``engine.py``, not here.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from accounts.models import District
from listings.models import Listing
from registry.models import RegistryEntry, UploadBatch


def check_same_district(run: "MatchRun", listing: Listing, entry: RegistryEntry | None) -> None:
    """A run covers one district; its listings and candidate registry entries must all belong to
    it (D63). Called by save(); services that use bulk_create must call it for every object."""
    if listing.district_id != run.district_id:
        raise ValidationError("listing district differs from the match run district")
    if entry is not None and entry.district_id != listing.district_id:
        raise ValidationError("registry entry district differs from the listing district")


class MatchRun(models.Model):
    """One matching run over one district. `params_version` makes results reproducible
    (AGENTS.md §8); `thresholds` holds the full parameter snapshot of that version (M4).
    The district is what officer scoping filters on (D63)."""

    district = models.ForeignKey(District, on_delete=models.PROTECT, related_name="match_runs")
    # The name of the parameter version used, for example "m5-tuned-1".
    params_version = models.CharField(max_length=32)
    # A full copy of every parameter value, so the run can be explained later.
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
    """One possible registry match for one listing in one run, with its score."""

    run = models.ForeignKey(MatchRun, on_delete=models.CASCADE, related_name="candidates")
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="candidates")
    registry_entry = models.ForeignKey(RegistryEntry, on_delete=models.PROTECT)
    score = models.FloatField()
    # Feature values for the officer's screen, plus the rules that found this candidate.
    features = models.JSONField(default=dict)
    rank = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [
            # The same registry entry may appear only once per listing in one run.
            models.UniqueConstraint(
                fields=["run", "listing", "registry_entry"], name="uniq_candidate_per_run"
            ),
        ]

    def save(self, *args, **kwargs) -> None:
        """Check the district rule, then save as normal."""
        check_same_district(self.run, self.listing, self.registry_entry)
        super().save(*args, **kwargs)


class MatchResult(models.Model):
    """Prioritises a listing for human review. Never a finding (AGENTS.md rule 1)."""

    class Status(models.TextChoices):
        """The three plain-word results an officer sees. Labels are translatable."""

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
    # Queue position: 1 is the most urgent. Used to sort the officer's list.
    priority = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            # Each listing gets exactly one result per run.
            models.UniqueConstraint(fields=["run", "listing"], name="uniq_result_per_run"),
        ]

    def save(self, *args, **kwargs) -> None:
        """Check the district rule, then save as normal."""
        check_same_district(self.run, self.listing, self.top_registry_entry)
        super().save(*args, **kwargs)


class GroundTruth(models.Model):
    """Synthetic evaluation labels (M1 `ground_truth.csv`). Used by the eval harness only;
    the matcher must never read this table (D35)."""

    class Type(models.TextChoices):
        """The kind of synthetic case. Each one tests a different situation."""

        CLEAN = "clean", "clean"  # a listing that matches its registry entry exactly
        NOISY = "noisy", "noisy"  # a match with typos or spelling differences
        WRONG_OR_EXPIRED = "wrong_or_expired", "wrong_or_expired"  # wrong or lapsed licence
        NO_COUNTERPART = "no_counterpart", "no_counterpart"  # no registry entry exists
        HARD_NEGATIVE = "hard_negative", "hard_negative"  # looks similar but is a different place

    listing = models.OneToOneField(Listing, on_delete=models.CASCADE, related_name="ground_truth")
    true_registry_entry = models.ForeignKey(
        RegistryEntry, null=True, blank=True, on_delete=models.PROTECT
    )
    type = models.CharField(max_length=32, choices=Type.choices)
    noise = models.CharField(max_length=100, blank=True)
