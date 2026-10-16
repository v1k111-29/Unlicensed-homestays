"""Matching engine: candidates, scoring and status bands (data-and-matching.md §5-7).

What this file is for: it decides, for every listing (a stay advertised online), which
registry entries (licensed homestays from the official list) it could be the same place as,
and how sure that is. The result is one "band" per listing.

Who calls it: ``matching.services.run_matching`` stores the results in the database, and the
evaluation harness in ``src/evaluation`` calls ``match`` directly on plain records.

Key idea in plain words: comparing every listing with every entry would be slow and noisy.
So the engine first finds a short list of likely entries (blocking), scores each pair with
weighted features (name, address, distance, and so on), then sorts the listing into a band.

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
# A "band" is the group a listing falls into. Each band maps to a status (matched,
# needs review, no match) and to a queue priority, see STATUS and PRIORITY below.
MATCHED_LICENCE = "matched_licence"  # claimed licence valid; name and locality consistent
MATCHED_SCORE = "matched_score"  # score >= T_high, no licence claimed (optional review)
MATCHED_CONFIRMED = "matched_confirmed"  # pair confirmed earlier by an officer (O4)
REVIEW_LICENCE = "review_licence"  # needs review, high priority: licence issue
REVIEW_SCORE = "review_score"  # needs review: T_low <= score < T_high, or several similar
NO_CANDIDATE = "no_candidate"  # no candidate >= T_low: needs review

# The order of this tuple is the order of the officer's queue (first = most urgent).
BANDS = (
    REVIEW_LICENCE,
    NO_CANDIDATE,
    REVIEW_SCORE,
    MATCHED_SCORE,
    MATCHED_LICENCE,
    MATCHED_CONFIRMED,
)
# Queue order (§7): licence issue -> no candidate -> ambiguous. Matched bands come last.
# Priority numbers start at 1, so 1 is the most urgent band.
PRIORITY = {band: n for n, band in enumerate(BANDS, start=1)}
# Each band's status, the plain-word result an officer sees in the list.
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
    """One registry entry that might be the same place as a listing, with its score."""

    registry_id: RecordId
    licence_no: str
    score: float  # weighted score from 0 to 1; higher means more alike
    rank: int  # 1 is the best candidate for this listing
    blocked_by: tuple[str, ...]  # the rules that let this entry into the short list
    features: dict  # each feature value, plus a "detail" dict an officer can read


@dataclass(frozen=True)
class Outcome:
    """The engine's answer for one listing: its band, the reasons and the candidates."""

    listing_id: RecordId
    band: str
    reasons: tuple[str, ...]  # short reason codes, shown to officers via labels
    score: float | None  # score of the top candidate, or None if there is none
    top_registry_id: RecordId | None  # the best registry entry, if one was chosen
    candidates: tuple[Candidate, ...]  # the candidates kept for storage

    @property
    def status(self) -> str:
        """Plain status for this band: matched, needs_review or no_match."""
        return STATUS[self.band]

    @property
    def priority(self) -> int:
        """Queue position for this band. 1 is the most urgent."""
        return PRIORITY[self.band]


# ------------------------------------------------------------ candidates


def _district_key(name: str) -> str:
    """Clean a district name so that spelling and case differences do not split a district."""
    return basic_clean(name)


def _id_key(record_id: RecordId) -> tuple[int, str]:
    """Sort key for record ids that may be numbers or text.

    Numbers come first and are zero-padded to 20 digits, so 10 sorts after 9. Text ids come
    after them. The leading 0 or 1 keeps the two kinds apart, so they are never compared
    directly (Python cannot compare an int with a str).
    """
    return (0, f"{record_id:020d}") if isinstance(record_id, int) else (1, str(record_id))


class RegistryIndex:
    """Blocking index for one district's registry (data-and-matching.md §5).

    Blocking means: store the entries under cheap keys (pincode, locality, licence, name
    key), so a listing only needs to be compared with the entries that share a key with it.
    """

    def __init__(self, entries: Iterable[PreparedRegistry]) -> None:
        # Sort once, so each entry has a fixed position number (its index) for the whole run.
        self.entries = sorted(entries, key=lambda e: (e.rec.licence_no, _id_key(e.rec.id)))
        # Each dict maps a key to the list of entry positions that have that key.
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
            # An entry can have several name keys, so it can be stored under several of them.
            for k in e.keys:
                self.by_key[k].append(i)

    def candidates(self, lst: PreparedListing, params: MatchParams) -> list[tuple[int, list[str]]]:
        """Indices of blocked entries with the rules that let each one in.

        Returns ``(entry position, [rule names])`` pairs, sorted by position. An entry that
        matches by several rules appears once with all of its rules.
        """
        # Maps an entry position to the list of rules that let it in.
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
        # Radius has no key to look up, so every entry with coordinates is checked by distance.
        if lst.point is not None:
            for i, e in enumerate(self.entries):
                if e.point is not None and haversine_km(lst.point, e.point) <= (
                    params.block_radius_km
                ):
                    hits[i].append("radius")
        # The name key rule adds an entry once, even if several of its keys match.
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
    """Score every blocked entry against the listing and return them ranked, best first.

    ``forced`` lists entry positions an officer confirmed earlier. They are added even if
    blocking did not find them, so a confirmed pair is always scored and kept.
    """
    blocked = dict(index.candidates(lst, params))
    for i in forced:
        blocked.setdefault(i, []).append("confirmed")
    rows = []
    for i, rules in blocked.items():
        reg = index.entries[i]
        feats = pair_features(lst, reg, params, as_of)
        rows.append((reg, weighted_score(feats, params), feats, tuple(rules)))
    # Rank: score, then name, then licence number and id (stable tie-break).
    # The minus signs make the higher score or name feature sort first.
    rows.sort(key=lambda r: (-r[1], -r[2]["name"], r[0].rec.licence_no, _id_key(r[0].rec.id)))
    return [
        Candidate(reg.rec.id, reg.rec.licence_no, score, rank, rules, feats)
        for rank, (reg, score, feats, rules) in enumerate(rows, start=1)
    ]


def _keep(cands: list[Candidate], params: MatchParams) -> tuple[Candidate, ...]:
    """Top N, plus any licence or confirmed hit ranked lower (officers must see it)."""
    # Storing every candidate would bloat the database. Keep the top N, but never drop a
    # licence hit or a confirmed pair, even when it ranks low.
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
    """Return ``(band, reason codes, top candidate)`` for one listing (§7).

    The checks run in a fixed order, and the first one that applies decides the band:
    an officer's earlier confirmation, then the claimed licence, then the score.
    """
    best = cands[0] if cands else None

    # Path 1: an officer confirmed this pair earlier. Only still-valid entries count.
    if confirmed is not None:
        if confirmed_valid:
            return MATCHED_CONFIRMED, ("confirmed_by_officer",), confirmed
        return REVIEW_LICENCE, ("confirmed_entry_not_valid",), confirmed

    # Path 2: the listing claims a licence number. The licence decides the band.
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
        # The place evidence is address, pincode and distance. A None value means "unknown".
        place = [f["address"], f["pincode"], f["distance"]]
        known = [v for v in place if v is not None]
        # The place counts as the same if any one of these checks passes.
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

    # Path 3: no licence claimed, so only the score counts.
    if best is None or best.score < params.t_low:
        return NO_CANDIDATE, ("no_candidate_above_t_low",), None
    if best.score >= params.t_high:
        second = cands[1] if len(cands) > 1 else None
        # Two very close top scores mean the listing could be either place, so an officer
        # must choose.
        if second is not None and best.score - second.score < params.ambiguity_margin:
            return REVIEW_SCORE, ("several_similar",), best
        if best.features["name"] < params.score_name_min:
            return REVIEW_SCORE, ("name_differs",), best
        return MATCHED_SCORE, ("score_above_t_high",), best
    # Between the two thresholds: a possible match that needs a human to decide.
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
    # Build one index per district. Listings are only ever compared inside their district.
    by_district: dict[str, list[PreparedRegistry]] = defaultdict(list)
    for rec in registry:
        by_district[_district_key(rec.district)].append(prepare_registry(rec, gazetteer, params))
    indexes = {d: RegistryIndex(entries) for d, entries in by_district.items()}
    # A listing whose district has no registry gets an empty index, so it becomes no candidate.
    empty = RegistryIndex([])
    confirmed = confirmed or {}

    outcomes = []
    # Sorting the listings makes the output order the same on every run.
    for rec in sorted(listings, key=lambda r: _id_key(r.id)):
        lst = prepare_listing(rec, gazetteer, params)
        index = indexes.get(_district_key(rec.district), empty)
        wanted = {str(x) for x in confirmed.get(rec.id, ())}
        forced = [i for i, e in enumerate(index.entries) if str(e.rec.id) in wanted]
        cands = _scored(lst, index, params, as_of, forced)

        # The first candidate with a licence hit, and the first with a confirmed hit.
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
        # The stored score is the chosen top candidate's score. If none was chosen, fall back
        # to the best score found, so the officer still sees a number.
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
