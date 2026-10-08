"""Officer-facing labels for the codes stored by the matching engine (M8).

The engine stores short codes (``match_results.reasons``, ``match_candidates.features``);
templates show these translatable labels instead. Wording describes what to check next and
never judges the stay (AGENTS.md rules 1-2). Unknown codes fall back to the code itself, so a
new engine code is visible rather than hidden.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.utils.translation import gettext_lazy as _

REASON_LABELS = {
    "confirmed_by_officer": _("An officer confirmed this registry entry earlier"),
    "confirmed_entry_not_valid": _(
        "An officer confirmed this registry entry earlier, but it is not valid on the run date"
    ),
    "licence_not_in_registry": _("Claimed licence number not found in this district's registry"),
    "licence_not_valid": _("Claimed licence is in the registry but not valid on the run date"),
    "licence_name_differs": _("Claimed licence found, but the name differs"),
    "licence_locality_differs": _("Claimed licence found, but the place differs"),
    "licence_valid_details_consistent": _("Claimed licence valid; name and place agree"),
    "no_candidate_above_t_low": _("No registry entry scored above the lower threshold"),
    "several_similar": _("Several registry entries scored almost the same"),
    "name_differs": _("High score, but the name differs"),
    "score_above_t_high": _("Score above the upper threshold"),
    "score_between_thresholds": _("Score between the lower and upper thresholds"),
}

FEATURE_LABELS = {
    "licence": _("Licence number"),
    "name": _("Name"),
    "address": _("Address / locality"),
    "distance": _("Distance"),
    "pincode": _("Pincode"),
    "category": _("Category"),
}
FEATURE_ORDER = ("licence", "name", "address", "distance", "pincode", "category")

BLOCK_LABELS = {
    "licence": _("same licence number"),
    "pincode": _("same pincode"),
    "locality": _("same locality"),
    "radius": _("nearby (within the search radius)"),
    "name_key": _("similar name"),
    "confirmed": _("confirmed earlier"),
}


def reason_labels(codes: Iterable[str]) -> list[str]:
    return [str(REASON_LABELS.get(code, code)) for code in codes or ()]


def block_labels(codes: Iterable[str]) -> list[str]:
    return [str(BLOCK_LABELS.get(code, code)) for code in codes or ()]


def feature_rows(features: dict) -> list[dict]:
    """Feature values in a fixed order; ``None`` means the information was missing."""
    return [
        {"key": key, "label": FEATURE_LABELS[key], "value": (features or {}).get(key)}
        for key in FEATURE_ORDER
    ]
