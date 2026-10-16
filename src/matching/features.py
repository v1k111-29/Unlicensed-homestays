"""Prepared records and per-pair features (data-and-matching.md §4, §6). Pure Python.

What this file is for: it turns raw registry and listing records into "prepared" records
(cleaned names, places and keys), then compares one listing with one registry entry on
several features (licence, name, address, distance, pincode, category).

Who calls it: ``matching.engine`` calls ``prepare_registry``, ``prepare_listing``,
``pair_features`` and ``weighted_score`` for every candidate pair.

Key idea in plain words: each record is cleaned once. Each feature is a number from 0 to 1,
where 1 means "the same" and 0 means "clearly different". A feature is ``None`` when the
information is missing on either side. Missing features are left out of the weighted mean,
so a listing without coordinates is not punished for it.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date

from rapidfuzz import fuzz

from matching.gazetteer import Gazetteer
from matching.normalise import (
    NormalisedText,
    basic_clean,
    normalise_address,
    normalise_name,
    phonetic_key,
)
from matching.params import MatchParams
from matching.records import ListingRecord, RegistryRecord

# ------------------------------------------------------------------ helpers

# Any character that is not a digit or an uppercase letter. Used to strip licence numbers.
_LICENCE_JUNK = re.compile(r"[^0-9A-Z]")


def licence_key(value: str) -> str:
    """Compare licence numbers without case, spaces or punctuation: ``syn-nlg 1`` == ``SYNNLG1``."""
    return _LICENCE_JUNK.sub("", (value or "").upper())


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Straight-line distance in kilometres between two (latitude, longitude) points.

    This is the great-circle distance over the Earth's surface, which is accurate enough for
    a search radius of a few kilometres.
    """
    lat1, lng1 = map(math.radians, a)
    lat2, lng2 = map(math.radians, b)
    # The haversine formula. h is the square of half the chord length between the points.
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    )
    # 6371.0088 is the mean Earth radius in kilometres.
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def _point(lat: float | None, lng: float | None) -> tuple[float, float] | None:
    """Turn a latitude and longitude pair into a point, or ``None`` if either is missing."""
    if lat is None or lng is None:
        return None
    return (float(lat), float(lng))


# Listing titles carry no category column; infer it from the generic words in the title.
# "stay" alone is ambiguous and gives no category.
_CATEGORY_WORDS: dict[str, str] = {
    "homestay": "homestay",
    "homestays": "homestay",
    "cottage": "cottage",
    "cottages": "cottage",
    "villa": "cottage",
    "villas": "cottage",
    "residency": "guest_house",
    "lodge": "lodge",
    "lodges": "lodge",
    "inn": "lodge",
    "hotel": "lodge",
}


def infer_category(tokens: tuple[str, ...]) -> str | None:
    """Guess the accommodation category from the words of a listing title.

    Returns ``None`` when no category word is found. "Guest house" is two words, so it is
    checked as a pair first.
    """
    for i, tok in enumerate(tokens):
        if tok == "guest" and i + 1 < len(tokens) and tokens[i + 1] == "house":
            return "guest_house"
        if tok in _CATEGORY_WORDS:
            return _CATEGORY_WORDS[tok]
    return None


# Words that name the region or district rather than a place inside it.
_DISTRICT_WORDS = frozenset({"district", "dist", "dt", "tamil", "nadu", "tn", "india"})


def _place_tokens(tokens: tuple[str, ...], district: str) -> tuple[str, ...]:
    """Drop the district name and generic region words: they say nothing about locality."""
    drop = set(basic_clean(district).split()) | _DISTRICT_WORDS
    return tuple(t for t in tokens if t not in drop)


def name_keys(name: NormalisedText, min_len: int) -> frozenset[str]:
    """Phonetic keys of the name core, used for candidate blocking.

    Keys shorter than ``min_len`` are left out. Short keys are too common to be useful for
    finding a short list of candidates.
    """
    keys = {k for k in name.keys if len(k) >= min_len}
    if len(name.compact) >= min_len:
        keys.add(phonetic_key(name.compact))
    return frozenset(keys)


# ---------------------------------------------------------------- prepared


@dataclass(frozen=True)
class PreparedRegistry:
    """A registry entry after cleaning: the original record plus the derived fields."""

    rec: RegistryRecord
    licence: str  # licence number with junk removed, for exact comparison
    name: NormalisedText
    address_tokens: tuple[str, ...]
    locality: str | None  # canonical locality, cleaned
    pincode: str | None
    point: tuple[float, float] | None
    keys: frozenset[str]  # blocking keys built from the name

    def is_valid(self, as_of: date) -> bool:
        """Active, and ``as_of`` lies inside the validity window."""
        r = self.rec
        # A missing status counts as active. Any other status (for example suspended) fails.
        if (r.status or "active") != "active":
            return False
        if r.valid_from is not None and r.valid_from > as_of:
            return False
        return r.valid_to >= as_of


@dataclass(frozen=True)
class PreparedListing:
    """A listing after cleaning: the original record plus the derived fields."""

    rec: ListingRecord
    licence: str  # claimed licence number with junk removed
    name: NormalisedText
    place_tokens: tuple[str, ...]
    locality: str | None
    locality_method: str  # exact | contains | phonetic | pincode | none
    pincode: str | None
    point: tuple[float, float] | None
    keys: frozenset[str]  # blocking keys built from the title
    category: str | None  # inferred from the title, for example "homestay"


def prepare_registry(rec: RegistryRecord, gaz: Gazetteer, params: MatchParams) -> PreparedRegistry:
    """Clean one registry entry so it can be compared quickly many times."""
    d = rec.district
    name = normalise_name(rec.name, d, gaz)
    addr = normalise_address(f"{rec.address_en} {rec.locality}", d, gaz)
    resolved = gaz.resolve(d, rec.locality)
    # Use the canonical locality name when the gazetteer knows it, else the cleaned raw text.
    locality = basic_clean(resolved.locality if resolved else rec.locality) or None
    # Prefer the entry's own pincode. If it has none, use a pincode found inside the address.
    pincode = (rec.pincode or "").strip() or addr.pincode
    return PreparedRegistry(
        rec=rec,
        licence=licence_key(rec.licence_no),
        name=name,
        address_tokens=_place_tokens(addr.tokens, d),
        locality=locality,
        pincode=pincode or None,
        point=_point(rec.lat, rec.lng),
        keys=name_keys(name, params.name_key_min_len),
    )


def prepare_listing(rec: ListingRecord, gaz: Gazetteer, params: MatchParams) -> PreparedListing:
    """Clean one listing so it can be compared quickly many times."""
    d = rec.district
    name = normalise_name(rec.title, d, gaz)
    place = normalise_address(rec.locality_text, d, gaz)
    pincode = (rec.pincode or "").strip() or place.pincode or None
    locality: str | None = None
    method = "none"
    resolved = gaz.resolve(d, rec.locality_text)
    if resolved is not None:
        locality, method = basic_clean(resolved.locality), resolved.method
    elif pincode:
        # No name match, so try the pincode. Only accept it when it names exactly one locality.
        names = gaz.localities_for_pincode(d, pincode)
        if len(names) == 1:
            locality, method = basic_clean(names[0]), "pincode"
    return PreparedListing(
        rec=rec,
        licence=licence_key(rec.claimed_licence_no),
        name=name,
        place_tokens=_place_tokens(place.tokens, d),
        locality=locality,
        locality_method=method,
        pincode=pincode,
        point=_point(rec.lat, rec.lng),
        keys=name_keys(name, params.name_key_min_len),
        category=infer_category(name.tokens),
    )


# ---------------------------------------------------------------- features

# The features, in the order they are computed and weighted. Names must match MatchParams.weights.
FEATURES = ("licence", "name", "address", "distance", "pincode", "category")


def _r(value: float) -> float:
    """Round to 4 decimals so tiny float differences do not change the result."""
    return round(value, 4)


def licence_feature(lst: PreparedListing, reg: PreparedRegistry, as_of: date) -> tuple:
    """Compare licence numbers. Returns ``(value, status)``.

    Value 1.0 is an exact match with a valid entry, 0.5 an exact match with a lapsed entry,
    0.0 a different number, and ``None`` means the listing claimed no licence at all.
    """
    if not lst.licence:
        return None, "absent"
    if lst.licence != reg.licence:
        return 0.0, "different"
    if reg.is_valid(as_of):
        return 1.0, "exact_valid"
    return 0.5, "exact_lapsed"


def name_feature(lst: PreparedListing, reg: PreparedRegistry) -> tuple[float, dict]:
    """Compare names three ways and keep the best. Returns ``(value, details)``.

    The three ways are: token set ratio (shared words), compact ratio (words joined
    together) and phonetic ratio (sound-alike keys). Each is a 0-100 score, divided by 100.
    """
    token_set = fuzz.token_set_ratio(lst.name.core, reg.name.core)
    compact = fuzz.ratio(lst.name.compact, reg.name.compact)
    # Sort ratio, not set ratio: phonetic keys are short and coarse, and a set ratio would
    # let one shared word dominate ("eukaliptus ritk" vs "eukaliptus kurt" -> 0.87).
    phonetic = fuzz.token_sort_ratio(" ".join(lst.name.keys), " ".join(reg.name.keys))
    value = max(token_set, compact, phonetic) / 100
    return _r(value), {
        "token_set": _r(token_set / 100),
        "compact": _r(compact / 100),
        "phonetic": _r(phonetic / 100),
    }


def address_feature(lst: PreparedListing, reg: PreparedRegistry) -> tuple:
    """Compare places. Returns ``(value, method)``.

    The same canonical locality gives 1.0 straight away. Otherwise the place words are
    compared as text. ``None`` means one side has no place words at all.
    """
    if lst.locality is not None and lst.locality == reg.locality:
        return 1.0, "same_locality"
    if not lst.place_tokens or not reg.address_tokens:
        return None, "missing"
    text = fuzz.token_set_ratio(" ".join(lst.place_tokens), " ".join(reg.address_tokens))
    return _r(text / 100), "text"


def distance_feature(
    lst: PreparedListing, reg: PreparedRegistry, params: MatchParams
) -> tuple[float | None, float | None]:
    """Turn the distance between two points into a score. Returns ``(score, km)``.

    The score halves for every ``distance_half_life_km`` of distance. So at the half-life
    distance the score is 0.5, and at twice that it is 0.25.
    """
    if lst.point is None or reg.point is None:
        return None, None
    km = haversine_km(lst.point, reg.point)
    return _r(0.5 ** (km / params.distance_half_life_km)), round(km, 3)


def pincode_feature(lst: PreparedListing, reg: PreparedRegistry) -> float | None:
    """1.0 if both pincodes are known and equal, 0.0 if known and different, else ``None``."""
    if not lst.pincode or not reg.pincode:
        return None
    return 1.0 if lst.pincode == reg.pincode else 0.0


def category_feature(lst: PreparedListing, reg: PreparedRegistry) -> float | None:
    """1.0 if both categories are known and equal, 0.0 if different, else ``None``."""
    if not lst.category or not reg.rec.category:
        return None
    return 1.0 if lst.category == reg.rec.category else 0.0


def pair_features(
    lst: PreparedListing, reg: PreparedRegistry, params: MatchParams, as_of: date
) -> dict:
    """All feature values for one pair, plus details an officer can read (stored as JSON)."""
    licence, licence_status = licence_feature(lst, reg, as_of)
    name, name_detail = name_feature(lst, reg)
    address, address_method = address_feature(lst, reg)
    distance, km = distance_feature(lst, reg, params)
    return {
        "licence": licence,
        "name": name,
        "address": address,
        "distance": distance,
        "pincode": pincode_feature(lst, reg),
        "category": category_feature(lst, reg),
        # The "detail" dict is for the officer's screen. It is not used in the score.
        "detail": {
            "licence_status": licence_status,
            "registry_valid": reg.is_valid(as_of),
            "name": name_detail,
            "address_method": address_method,
            "listing_locality": lst.locality,
            "listing_locality_method": lst.locality_method,
            "registry_locality": reg.locality,
            "distance_km": km,
            "listing_category": lst.category,
            "registry_category": reg.rec.category or None,
        },
    }


def weighted_score(features: dict, params: MatchParams) -> float:
    """Weighted mean over the features that are present (data-and-matching.md §6)."""
    total = 0.0
    weight_sum = 0.0
    for name in FEATURES:
        value = features[name]
        # Skip missing features completely, so they do not drag the mean down.
        if value is None:
            continue
        w = getattr(params.weights, name)
        total += w * value
        weight_sum += w
    # If every feature was missing, there is nothing to score.
    if weight_sum == 0:
        return 0.0
    # Dividing by the weight sum keeps the result between 0 and 1 even when features are left out.
    return round(total / weight_sum, params.score_decimals)
