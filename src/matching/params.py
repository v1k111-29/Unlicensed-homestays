"""Versioned matching parameters (data-and-matching.md §6-7). Pure Python, no Django.

What this file is for: it holds every number that controls matching (feature weights,
band thresholds, search radius). Each set of numbers has a version name, so an old run can
always be repeated with the exact same numbers.

Who calls it: ``matching.engine`` and ``matching.services`` read the parameters. The
evaluation harness in ``src/evaluation`` reads them to tune and to check results.

Every match run stores ``params_version`` and a full snapshot of these values, so the same
inputs plus the same version always give the same outputs (AGENTS.md §8).

Rule: never change the values of a published version. Add a new version instead and point
``CURRENT_VERSION`` at it. ``tests/test_matching_params.py`` pins the fingerprint of every
version, so an in-place edit fails the test suite.

All numbers are starting values [A]. They were chosen by inspecting the dev set only, never
the test set (AGENTS.md rule 9). M5 tunes them on dev and publishes a new version.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Weights:
    """Feature weights from data-and-matching.md §6. They sum to 1.0."""

    # The licence number counts most, because it is the official identifier.
    licence: float = 0.30
    name: float = 0.25
    address: float = 0.20
    distance: float = 0.15
    pincode: float = 0.05
    category: float = 0.05


@dataclass(frozen=True)
class MatchParams:
    """One complete, frozen set of matching numbers under one version name."""

    version: str
    weights: Weights = field(default_factory=Weights)
    # Status bands (§7). Scores are rounded to ``score_decimals`` before comparison.
    # A score below t_low is "no candidate"; t_low to t_high is "needs review".
    t_low: float = 0.75
    t_high: float = 0.90
    # Two candidates both >= t_high and closer than this margin -> "Needs review".
    ambiguity_margin: float = 0.05
    # Licence path: name and locality must be consistent for an automatic match.
    licence_name_min: float = 0.80
    # Score path (no licence claimed): the name must agree too, not only the place.
    score_name_min: float = 0.85
    # Candidate generation (§5): same district AND (pincode | locality | radius | licence
    # | shared name key).
    block_radius_km: float = 2.0
    # Name keys shorter than this are ignored, because short keys match too many names.
    name_key_min_len: int = 4
    # Distance decay: feature = 0.5 ** (km / half_life).
    distance_half_life_km: float = 1.0
    # Candidates stored per listing (the licence-hit entry is always kept as well).
    max_stored_candidates: int = 10
    # Scores are rounded to this many decimals, so tiny float differences do not matter.
    score_decimals: int = 4

    def snapshot(self) -> dict:
        """JSON-safe dict of every value (stored in ``match_runs.thresholds``)."""
        return asdict(self)

    def fingerprint(self) -> str:
        """Short hash of every value. A changed number gives a different fingerprint."""
        # sort_keys and compact separators make the text the same on every run.
        blob = json.dumps(self.snapshot(), sort_keys=True, separators=(",", ":"))
        # The first 16 hex characters are enough to spot a change.
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# Every published version, keyed by its name. Never edit a published entry (see above).
PARAMS: dict[str, MatchParams] = {
    "m4-initial-1": MatchParams(version="m4-initial-1"),
    # M5: tuned on the DEV set only, by widening the dev gap between true and false pairs and
    # putting each threshold mid-gap (D55). The test set was not used for any choice.
    "m5-tuned-1": MatchParams(
        version="m5-tuned-1",
        weights=Weights(
            licence=0.30, name=0.40, address=0.10, distance=0.10, pincode=0.05, category=0.05
        ),
        t_low=0.75,
        t_high=0.89,
        licence_name_min=0.75,
    ),
}
# The version used when no other version is asked for.
CURRENT_VERSION = "m5-tuned-1"


def get_params(version: str = CURRENT_VERSION) -> MatchParams:
    """Return the parameter set for ``version``. Raises ``KeyError`` for an unknown version."""
    try:
        return PARAMS[version]
    except KeyError:
        raise KeyError(f"unknown matching params version {version!r}") from None
