"""Matching engine: candidates, scoring and status bands (data-and-matching.md §5-7).

Pure Python, no Django, no I/O. ``match`` takes plain records and returns plain outcomes;
``services.run_matching`` stores them. The engine never reads ground truth (D35).

The result prioritises a listing for human review. It is never a finding about the stay
(AGENTS.md rule 1): the bands below only order the officer's queue.

Determinism: inputs are sorted by stable keys, every float is rounded before it is compared,
and ties are broken by licence number and record id. Same inputs + same params version =
same outputs.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from matching.features import (
    PreparedListing,
    PreparedRegistry,
    haversine_km,
    pair_features,
    prepare_listing,
    prepare_registry,
    weighted_score,
)
from matching.gazetteer import Gazetteer
from matching.normalise import basic_clean
from matching.params import MatchParams
from matching.records import ListingRecord, RecordId, RegistryRecord

# ------------------------------------------------------------------ bands
# Band keys (stored in ``match_results.band``; user-facing labels live in matching.models).
MATCHED_LICENCE = "matched_licence"  # claimed licence valid; name and locality consistent
MATCHED_SCORE = "matched_score"  # score >= T_high, no licence claimed (optional review)
MATCHED_CONFIRMED = "matched_confirmed"  # pair confirmed earlier by an officer (O4)
REVIEW_LICENCE = "review_licence"  # needs review, high priority: licence issue
REVIEW_SCORE = "review_score"  # needs review: T_low <= score < T_high, or several similar
NO_CANDIDATE = "no_candidate"  # no candidate >= T_low: needs review

BANDS = (
    REVIEW_LICENCE,
    NO_CANDIDATE,
    REVIEW_SCORE,
    MATCHED_SCORE,
    MATCHED_LICENCE,
    MATCHED_CONFIRMED,
)
# Queue order (§7): licence issue -> no candidate -> ambiguous. Matched bands come last.
PRIORITY = {band: n for n, band in enumerate(BANDS, start=1)}
STATUS = {
    MATCHED_LICENCE: "matched",
    MATCHED_SCORE: "matched",
    MATCHED_CONFIRMED: "matched",
    REVIEW_LICENCE: "needs_review",
    REVIEW_SCORE: "needs_review",
    NO_CANDIDATE: "no_match",
}


@dataclass(frozen=True)
class Candidate:
    registry_id: RecordId
    licence_no: str
    score: float
    rank: int
    blocked_by: tuple[str, ...]
    features: dict


@dataclass(frozen=True)
class Outcome:
    listing_id: RecordId
    band: str
    reasons: tuple[str, ...]
    score: float | None
    top_registry_id: RecordId | None
    candidates: tuple[Candidate, ...]

    @property
    def status(self) -> str:
        return STATUS[self.band]

    @property
    def priority(self) -> int:
        return PRIORITY[self.band]


# ------------------------------------------------------------ candidates


def _district_key(name: str) -> str:
    return basic_clean(name)


def _id_key(record_id: RecordId) -> tuple[int, str]:
    return (0, f"{record_id:020d}") if isinstance(record_id, int) else (1, str(record_id))


class RegistryIndex:
    """Blocking index for one district's registry (data-and-matching.md §5)."""

    def __init__(self, entries: Iterable[PreparedRegistry]) -> None:
        self.entries = sorted(entries, key=lambda e: (e.rec.licence_no, _id_key(e.rec.id)))
        self.by_pincode: dict[str, list[int]] = defaultdict(list)
        self.by_locality: dict[str, list[int]] = defaultdict(list)
        self.by_licence: dict[str, list[int]] = defaultdict(list)
        self.by_key: dict[str, list[int]] = defaultdict(list)
        for i, e in enumerate(self.entries):
            if e.pincode:
                self.by_pincode[e.pincode].append(i)
            if e.locality:
                self.by_locality[e.locality].append(i)
            if e.licence:
                self.by_licence[e.licence].append(i)
            for k in e.keys:
                self.by_key[k].append(i)

    def candidates(self, lst: PreparedListing, params: MatchParams) -> list[tuple[int, list[str]]]:
        """Indices of blocked entries with the rules that let each one in."""
        hits: dict[int, list[str]] = defaultdict(list)
        if lst.licence:
            for i in self.by_licence.get(lst.licence, []):
                hits[i].append("licence")
        if lst.pincode:
            for i in self.by_pincode.get(lst.pincode, []):
                hits[i].append("pincode")
        if lst.locality:
            for i in self.by_locality.get(lst.locality, []):
                hits[i].append("locality")
        if lst.point is not None:
            for i, e in enumerate(self.entries):
                if e.point is not None and haversine_km(lst.point, e.point) <= (
                    params.block_radius_km
                ):
                    hits[i].append("radius")
        for k in sorted(lst.keys):
            for i in self.by_key.get(k, []):
                if "name_key" not in hits[i]:
                    hits[i].append("name_key")
        return sorted(hits.items())


# ---------------------------------------------------------------- scoring


def _scored(
    lst: PreparedListing,
    index: RegistryIndex,
    params: MatchParams,
    as_of: date,
    forced: Iterable[int] = (),
) -> list[Candidate]:
    blocked = dict(index.candidates(lst, params))
    for i in forced:
        blocked.setdefault(i, []).append("confirmed")
    rows = []
    for i, rules in blocked.items():
        reg = index.entries[i]
        feats = pair_features(lst, reg, params, as_of)
        rows.append((reg, weighted_score(feats, params), feats, tuple(rules)))
    # Rank: score, then name, then licence number and id (stable tie-break).
    rows.sort(key=lambda r: (-r[1], -r[2]["name"], r[0].rec.licence_no, _id_key(r[0].rec.id)))
    return [
        Candidate(reg.rec.id, reg.rec.licence_no, score, rank, rules, feats)
        for rank, (reg, score, feats, rules) in enumerate(rows, start=1)
    ]


def _keep(cands: list[Candidate], params: MatchParams) -> tuple[Candidate, ...]:
    """Top N, plus any licence or confirmed hit ranked lower (officers must see it)."""
    keep = [
        c
        for c in cands
        if c.rank <= params.max_stored_candidates
        or "licence" in c.blocked_by
        or "confirmed" in c.blocked_by
    ]
    return tuple(keep)


# ------------------------------------------------------------------ bands


def assign_band(
    lst: PreparedListing,
    cands: Sequence[Candidate],
    params: MatchParams,
    *,
    licence_hit: Candidate | None,
    licence_hit_valid: bool,
    confirmed: Candidate | None = None,
    confirmed_valid: bool = True,
) -> tuple[str, tuple[str, ...], Candidate | None]:
    """Return ``(band, reason codes, top candidate)`` for one listing (§7)."""
    best = cands[0] if cands else None

    if confirmed is not None:
        if confirmed_valid:
            return MATCHED_CONFIRMED, ("confirmed_by_officer",), confirmed
        return REVIEW_LICENCE, ("confirmed_entry_not_valid",), confirmed

    if lst.licence:
        if licence_hit is None:
            return REVIEW_LICENCE, ("licence_not_in_registry",), best
        if not licence_hit_valid:
            return REVIEW_LICENCE, ("licence_not_valid",), licence_hit
        f = licence_hit.features
        reasons = []
        if f["name"] < params.licence_name_min:
            reasons.append("licence_name_differs")
        # Locality is consistent if any place evidence agrees; unknown place is not counted
        # against the listing (district already agrees and licence + name agree).
        place = [f["address"], f["pincode"], f["distance"]]
        known = [v for v in place if v is not None]
        locality_ok = (
            f["detail"]["address_method"] == "same_locality"
            or f["pincode"] == 1.0
            or (
                f["detail"]["distance_km"] is not None
                and f["detail"]["distance_km"] <= params.block_radius_km
            )
            or not known
        )
        if not locality_ok:
            reasons.append("licence_locality_differs")
        if reasons:
            return REVIEW_LICENCE, tuple(reasons), licence_hit
        return MATCHED_LICENCE, ("licence_valid_details_consistent",), licence_hit

    if best is None or best.score < params.t_low:
        return NO_CANDIDATE, ("no_candidate_above_t_low",), None
    if best.score >= params.t_high:
        second = cands[1] if len(cands) > 1 else None
        if second is not None and best.score - second.score < params.ambiguity_margin:
            return REVIEW_SCORE, ("several_similar",), best
        if best.features["name"] < params.score_name_min:
            return REVIEW_SCORE, ("name_differs",), best
        return MATCHED_SCORE, ("score_above_t_high",), best
    return REVIEW_SCORE, ("score_between_thresholds",), best


# ------------------------------------------------------------------- run


def match(
    listings: Sequence[ListingRecord],
    registry: Sequence[RegistryRecord],
    params: MatchParams,
    *,
    as_of: date,
    gazetteer: Gazetteer,
    confirmed: Mapping[RecordId, Iterable[RecordId]] | None = None,
) -> list[Outcome]:
    """Match every listing against registry entries of its own district only.

    ``confirmed`` maps a listing id to registry ids an officer confirmed earlier; such
    pairs are not flagged again (O4) while the entry is still valid.
    """
    by_district: dict[str, list[PreparedRegistry]] = defaultdict(list)
    for rec in registry:
        by_district[_district_key(rec.district)].append(prepare_registry(rec, gazetteer, params))
    indexes = {d: RegistryIndex(entries) for d, entries in by_district.items()}
    empty = RegistryIndex([])
    confirmed = confirmed or {}

    outcomes = []
    for rec in sorted(listings, key=lambda r: _id_key(r.id)):
        lst = prepare_listing(rec, gazetteer, params)
        index = indexes.get(_district_key(rec.district), empty)
        wanted = {str(x) for x in confirmed.get(rec.id, ())}
        forced = [i for i, e in enumerate(index.entries) if str(e.rec.id) in wanted]
        cands = _scored(lst, index, params, as_of, forced)

        licence_hit = next((c for c in cands if "licence" in c.blocked_by), None)
        confirmed_hit = next((c for c in cands if "confirmed" in c.blocked_by), None)
        by_id = {e.rec.id: e for e in index.entries}

        band, reasons, top = assign_band(
            lst,
            cands,
            params,
            licence_hit=licence_hit,
            licence_hit_valid=bool(licence_hit and by_id[licence_hit.registry_id].is_valid(as_of)),
            confirmed=confirmed_hit,
            confirmed_valid=bool(
                confirmed_hit and by_id[confirmed_hit.registry_id].is_valid(as_of)
            ),
        )
        best = cands[0].score if cands else None
        outcomes.append(
            Outcome(
                listing_id=rec.id,
                band=band,
                reasons=reasons,
                score=top.score if top is not None else best,
                top_registry_id=top.registry_id if top is not None else None,
                candidates=_keep(cands, params),
            )
        )
    return outcomes
