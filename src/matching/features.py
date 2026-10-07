"""Prepared records and per-pair features (data-and-matching.md §4, §6). Pure Python.

Each record is normalised once (``prepare_registry`` / ``prepare_listing``); the feature
functions then compare two prepared records. Every feature is a number in [0, 1] or ``None``
when the information is missing on either side. Missing features are left out of the
weighted mean, so a listing without coordinates is not punished for it.
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

_LICENCE_JUNK = re.compile(r"[^0-9A-Z]")


def licence_key(value: str) -> str:
    """Compare licence numbers without case, spaces or punctuation: ``syn-nlg 1`` == ``SYNNLG1``."""
    return _LICENCE_JUNK.sub("", (value or "").upper())


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1 = map(math.radians, a)
    lat2, lng2 = map(math.radians, b)
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    )
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def _point(lat: float | None, lng: float | None) -> tuple[float, float] | None:
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
    for i, tok in enumerate(tokens):
        if tok == "guest" and i + 1 < len(tokens) and tokens[i + 1] == "house":
            return "guest_house"
        if tok in _CATEGORY_WORDS:
            return _CATEGORY_WORDS[tok]
    return None


_DISTRICT_WORDS = frozenset({"district", "dist", "dt", "tamil", "nadu", "tn", "india"})


def _place_tokens(tokens: tuple[str, ...], district: str) -> tuple[str, ...]:
    """Drop the district name and generic region words: they say nothing about locality."""
    drop = set(basic_clean(district).split()) | _DISTRICT_WORDS
    return tuple(t for t in tokens if t not in drop)


def name_keys(name: NormalisedText, min_len: int) -> frozenset[str]:
    """Phonetic keys of the name core, used for candidate blocking."""
    keys = {k for k in name.keys if len(k) >= min_len}
    if len(name.compact) >= min_len:
        keys.add(phonetic_key(name.compact))
    return frozenset(keys)


# ---------------------------------------------------------------- prepared


@dataclass(frozen=True)
class PreparedRegistry:
    rec: RegistryRecord
    licence: str
    name: NormalisedText
    address_tokens: tuple[str, ...]
    locality: str | None  # canonical locality, cleaned
    pincode: str | None
    point: tuple[float, float] | None
    keys: frozenset[str]

    def is_valid(self, as_of: date) -> bool:
        """Active, and ``as_of`` lies inside the validity window."""
        r = self.rec
        if (r.status or "active") != "active":
            return False
        if r.valid_from is not None and r.valid_from > as_of:
            return False
        return r.valid_to >= as_of


@dataclass(frozen=True)
class PreparedListing:
    rec: ListingRecord
    licence: str
    name: NormalisedText
    place_tokens: tuple[str, ...]
    locality: str | None
    locality_method: str  # exact | contains | phonetic | pincode | none
    pincode: str | None
    point: tuple[float, float] | None
    keys: frozenset[str]
    category: str | None


def prepare_registry(rec: RegistryRecord, gaz: Gazetteer, params: MatchParams) -> PreparedRegistry:
    d = rec.district
    name = normalise_name(rec.name, d, gaz)
    addr = normalise_address(f"{rec.address_en} {rec.locality}", d, gaz)
    resolved = gaz.resolve(d, rec.locality)
    locality = basic_clean(resolved.locality if resolved else rec.locality) or None
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

FEATURES = ("licence", "name", "address", "distance", "pincode", "category")


def _r(value: float) -> float:
    return round(value, 4)


def licence_feature(lst: PreparedListing, reg: PreparedRegistry, as_of: date) -> tuple:
    if not lst.licence:
        return None, "absent"
    if lst.licence != reg.licence:
        return 0.0, "different"
    if reg.is_valid(as_of):
        return 1.0, "exact_valid"
    return 0.5, "exact_lapsed"


def name_feature(lst: PreparedListing, reg: PreparedRegistry) -> tuple[float, dict]:
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
    if lst.locality is not None and lst.locality == reg.locality:
        return 1.0, "same_locality"
    if not lst.place_tokens or not reg.address_tokens:
        return None, "missing"
    text = fuzz.token_set_ratio(" ".join(lst.place_tokens), " ".join(reg.address_tokens))
    return _r(text / 100), "text"


def distance_feature(
    lst: PreparedListing, reg: PreparedRegistry, params: MatchParams
) -> tuple[float | None, float | None]:
    if lst.point is None or reg.point is None:
        return None, None
    km = haversine_km(lst.point, reg.point)
    return _r(0.5 ** (km / params.distance_half_life_km)), round(km, 3)


def pincode_feature(lst: PreparedListing, reg: PreparedRegistry) -> float | None:
    if not lst.pincode or not reg.pincode:
        return None
    return 1.0 if lst.pincode == reg.pincode else 0.0


def category_feature(lst: PreparedListing, reg: PreparedRegistry) -> float | None:
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
        if value is None:
            continue
        w = getattr(params.weights, name)
        total += w * value
        weight_sum += w
    if weight_sum == 0:
        return 0.0
    return round(total / weight_sum, params.score_decimals)
