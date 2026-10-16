"""Officer-facing labels for the codes stored by the matching engine (M8).

What this file is for: the engine stores short codes such as ``licence_not_valid``. This
file maps each code to a sentence an officer can read. Labels are wrapped in ``gettext_lazy``
so the Tamil translation catalogue (``src/locale/ta``) can translate them.

Who calls it: ``src/reviews/views.py`` uses the ``*_labels`` helpers and ``feature_rows``
to show the reasons and scores on the case page.

The engine stores short codes (``match_results.reasons``, ``match_candidates.features``);
templates show these translatable labels instead. Wording describes what to check next and
never judges the stay (AGENTS.md rules 1-2). Unknown codes fall back to the code itself, so a
new engine code is visible rather than hidden.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.utils.translation import gettext_lazy as _

# Reason codes from ``engine.assign_band``, one sentence each.
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

# Feature names (the keys in a candidate's features) and their column titles.
FEATURE_LABELS = {
    "licence": _("Licence number"),
    "name": _("Name"),
    "address": _("Address / locality"),
    "distance": _("Distance"),
    "pincode": _("Pincode"),
    "category": _("Category"),
}
# The order the features are shown in on screen. Matches ``features.FEATURES``.
FEATURE_ORDER = ("licence", "name", "address", "distance", "pincode", "category")

# Blocking rule codes (why a candidate was found at all), see ``engine.RegistryIndex``.
BLOCK_LABELS = {
    "licence": _("same licence number"),
    "pincode": _("same pincode"),
    "locality": _("same locality"),
    "radius": _("nearby (within the search radius)"),
    "name_key": _("similar name"),
    "confirmed": _("confirmed earlier"),
}


def reason_labels(codes: Iterable[str]) -> list[str]:
    """Turn reason codes into readable sentences. Unknown codes are shown as they are."""
    return [str(REASON_LABELS.get(code, code)) for code in codes or ()]


def block_labels(codes: Iterable[str]) -> list[str]:
    """Turn blocking rule codes into readable phrases. Unknown codes are shown as they are."""
    return [str(BLOCK_LABELS.get(code, code)) for code in codes or ()]


def feature_rows(features: dict) -> list[dict]:
    """Feature values in a fixed order; ``None`` means the information was missing."""
    # ``features or {}`` handles a missing features dict, so every row is still produced.
    return [
        {"key": key, "label": FEATURE_LABELS[key], "value": (features or {}).get(key)}
        for key in FEATURE_ORDER
    ]
