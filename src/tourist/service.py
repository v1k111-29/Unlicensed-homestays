"""Tourist check (essentialfeatures.md T1): look a stay up in the registry.

This module is a thin layer over the matching code. It reuses the normaliser from M3 and the
feature functions from ``matching.features``. The view in ``tourist.views`` only handles HTTP;
all the checking logic is here. The service:

- reads the registry only (never listings, match results or ``GroundTruth``);
- is deterministic: same registry batch + same params version + same query = same answer;
- returns public fields only (``PublicEntry``: name, locality, category, validity), never
  licence numbers of other entries, addresses, coordinates or internal ids;
- logs one ``TouristCheck`` row per completed check (result type + timestamp only).

Outcomes (ui-design-brief.md §10): found, differs (details differ or not valid on the date
checked), several (more than one plausible entry), not_found.

Reading order for a newcomer: ``check`` is the entry point. It calls ``_licence_path`` when a
licence number is given, and ``_name_path`` when only a name and locality are given.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from accounts.models import District
from matching.features import (
    PreparedRegistry,
    address_feature,
    licence_key,
    name_feature,
    pair_features,
    prepare_listing,
    prepare_registry,
    weighted_score,
)
from matching.params import CURRENT_VERSION, MatchParams, get_params
from matching.records import ListingRecord
from matching.services import _registry_record as registry_record
from matching.services import default_as_of, default_gazetteer
from registry.models import RESERVED_DATASETS, RegistryEntry, UploadBatch
from tourist.models import TouristCheck

Result = TouristCheck.Result

# Most entries listed when the answer is "several possible matches". Keeps the page short.
MAX_SHOWN = 5


class RegistryUnavailable(Exception):
    """Raised when no registry has been loaded yet, so no check can be answered."""


@dataclass(frozen=True)
class Query:
    """What the tourist typed: a licence number, or a name and locality, plus an optional
    district. Empty strings mean "not given"."""

    licence: str = ""
    name: str = ""
    locality: str = ""
    district_id: int | None = None


@dataclass(frozen=True)
class PublicEntry:
    """The only registry fields a tourist may see (security-and-privacy.md §3).

    Anything else on a registry row (licence numbers of other entries, addresses,
    coordinates, internal ids) is deliberately left out of this class.
    """

    name: str
    locality: str
    category: str  # translated label, "" when unknown
    status: str  # translated label (Active / Expired / Suspended)
    valid_from: date | None
    valid_to: date
    valid_on_date: bool


@dataclass(frozen=True)
class CheckResult:
    """The answer to one check.

    `outcome` is one of the TouristCheck.Result values. `differences` lists the keys of
    `wording.DIFFERENCE_TEXT` that explain a "differs" answer. `as_of` is the date the
    validity was checked against.
    """

    outcome: str  # TouristCheck.Result value
    entries: tuple[PublicEntry, ...] = ()
    differences: tuple[str, ...] = ()  # keys of wording.DIFFERENCE_TEXT
    as_of: date | None = None


def current_registry_batch() -> UploadBatch:
    """Return the newest registry batch that tourists may search (Q17 default: newest is current).

    Reserved datasets (for example demo or test data) are skipped. Raises RegistryUnavailable
    when no batch qualifies.
    """
    batch = (
        UploadBatch.objects.filter(type=UploadBatch.Type.REGISTRY)
        .exclude(dataset__in=RESERVED_DATASETS)
        .order_by("-created_at", "-id")
        .first()
    )
    if batch is None:
        raise RegistryUnavailable
    return batch


# Registry batches never change after confirm (a new upload is a new batch), so prepared
# entries can be kept per (batch, params version). Small: at most a few batches.
_prepared: dict[tuple, tuple[PreparedRegistry, ...]] = {}
_MAX_CACHED = 4


def _prepared_registry(batch: UploadBatch, params: MatchParams) -> tuple[PreparedRegistry, ...]:
    """Return the prepared registry rows for a batch, building and caching them on first use.

    The cache is capped at `_MAX_CACHED` batches. When it is full, the oldest entry is
    dropped first.
    """
    # Primary keys can be reused after a rollback, so the key also carries hash and time.
    key = (batch.pk, batch.file_sha256, batch.created_at.isoformat(), params.version)
    if key not in _prepared:
        gaz = default_gazetteer()
        rows = RegistryEntry.objects.filter(batch=batch).select_related("district").order_by("pk")
        _prepared[key] = tuple(prepare_registry(registry_record(e), gaz, params) for e in rows)
        # Evict the oldest cached batch (dicts keep insertion order).
        while len(_prepared) > _MAX_CACHED:
            _prepared.pop(next(iter(_prepared)))
    return _prepared[key]


def _public(reg: PreparedRegistry, as_of: date) -> PublicEntry:
    """Turn a prepared registry row into the public view a tourist may see.

    Unknown category or status codes are shown as they are rather than hidden.
    """
    r = reg.rec
    category = RegistryEntry.Category(r.category).label if r.category else ""
    try:
        status = RegistryEntry.Status(r.status).label
    except ValueError:
        status = r.status
    return PublicEntry(
        name=r.name,
        locality=r.locality,
        category=str(category),
        status=str(status),
        valid_from=r.valid_from,
        valid_to=r.valid_to,
        valid_on_date=reg.is_valid(as_of),
    )


def _rank_key(score: float, name: float, reg: PreparedRegistry) -> tuple:
    """Sort key for candidates: best score first, then best name, then a fixed tie-break.

    The licence number and the id break exact ties, so the order is the same on every run
    (the matching must be deterministic).
    """
    return (-score, -name, reg.rec.licence_no, str(reg.rec.id))


def _listing(q: Query, district: str) -> ListingRecord:
    """Build the listing-side record the matcher compares against registry rows.

    Id 0 is a placeholder: a tourist query is not a stored listing.
    """
    return ListingRecord(id=0, title=q.name, locality_text=q.locality, district=district)


def _licence_path(
    q: Query, hits: list[PreparedRegistry], params: MatchParams, as_of: date
) -> CheckResult:
    """Answer a query whose licence number is in the registry.

    Checks the validity date, and the name and locality if the tourist gave them. Several hits
    (the same licence in two districts) give "several" so the tourist can choose.
    """
    if len(hits) > 1:  # same licence number in two districts: let the tourist choose
        hits.sort(key=lambda r: (r.rec.district, r.rec.name))
        return CheckResult(Result.SEVERAL, tuple(_public(r, as_of) for r in hits[:MAX_SHOWN]))
    reg = hits[0]
    diffs: list[str] = []
    if not reg.is_valid(as_of):
        diffs.append("validity")
    if q.name or q.locality:
        lst = prepare_listing(_listing(q, reg.rec.district), default_gazetteer(), params)
        if q.name and name_feature(lst, reg)[0] < params.licence_name_min:
            diffs.append("name")
        if q.locality:
            value, method = address_feature(lst, reg)
            # A locality that is "the same locality" counts as agreeing, even with no score.
            if method != "same_locality" and (value is None or value < params.licence_name_min):
                diffs.append("locality")
    outcome = Result.DIFFERS if diffs else Result.FOUND
    return CheckResult(outcome, (_public(reg, as_of),), tuple(diffs))


def _name_path(
    q: Query, entries: tuple[PreparedRegistry, ...], params: MatchParams, as_of: date
) -> CheckResult:
    """Answer a query with no licence match, by scoring every registry row on name and place.

    Entries are scored district by district. A single clearly best entry gives "found" or
    "differs". Several close entries give "several". A single plausible entry that is not
    confident enough also gives "differs". No entry above the lowest threshold gives
    "not found".
    """
    gaz = default_gazetteer()
    districts = sorted({e.rec.district for e in entries})
    scored: list[tuple[float, float, str, PreparedRegistry]] = []
    for district in districts:
        lst = prepare_listing(_listing(q, district), gaz, params)
        for reg in entries:
            if reg.rec.district != district:
                continue
            feats = pair_features(lst, reg, params, as_of)
            method = feats["detail"]["address_method"]
            scored.append((weighted_score(feats, params), feats["name"], method, reg))
    scored.sort(key=lambda s: _rank_key(s[0], s[1], s[3]))

    # Same thresholds as the officer bands (params version CURRENT_VERSION): a confident match
    # needs score >= T_high and a close name; a plausible one score >= T_low.
    strong = [s for s in scored if s[0] >= params.t_high and s[1] >= params.score_name_min]
    near = [s for s in scored if s[0] >= params.t_low and s[1] >= params.licence_name_min]
    if strong:
        # Entries whose score is within the ambiguity margin of the best one are "close".
        # One close entry means a clear answer. Two or more mean the tourist must choose.
        close = [s for s in strong if strong[0][0] - s[0] < params.ambiguity_margin]
        if len(close) == 1:
            reg = close[0][3]
            diffs = () if reg.is_valid(as_of) else ("validity",)
            outcome = Result.DIFFERS if diffs else Result.FOUND
            return CheckResult(outcome, (_public(reg, as_of),), diffs)
        return CheckResult(Result.SEVERAL, tuple(_public(s[3], as_of) for s in close[:MAX_SHOWN]))
    if len(near) == 1:
        score, name, method, reg = near[0]
        diffs_list = []
        if not reg.is_valid(as_of):
            diffs_list.append("validity")
        if name < params.score_name_min:
            diffs_list.append("name")
        if method != "same_locality":
            diffs_list.append("locality")
        # Between the two thresholds with no named difference: say the name is the doubt.
        if not diffs_list:
            diffs_list.append("name")
        return CheckResult(Result.DIFFERS, (_public(reg, as_of),), tuple(diffs_list))
    if near:
        return CheckResult(Result.SEVERAL, tuple(_public(s[3], as_of) for s in near[:MAX_SHOWN]))
    return CheckResult(Result.NOT_FOUND)


def check(q: Query, *, batch: UploadBatch | None = None) -> CheckResult:
    """Answer one tourist query. Raises ``RegistryUnavailable`` when no registry exists.

    A licence number is tried first. If it is not in the registry but a name and locality were
    also given, the name-and-place search runs. If that search finds a match, it is reported as
    "differs", because the licence number itself did not match.
    """
    batch = batch or current_registry_batch()
    params = get_params(CURRENT_VERSION)
    as_of = default_as_of(batch)
    entries = _prepared_registry(batch, params)
    if q.district_id is not None:
        name = District.objects.filter(pk=q.district_id).values_list("name_en", flat=True).first()
        entries = tuple(e for e in entries if e.rec.district == name)

    result = CheckResult(Result.NOT_FOUND)
    key = licence_key(q.licence)
    if key:
        hits = [e for e in entries if e.licence == key]
        if hits:
            result = _licence_path(q, hits, params, as_of)
        elif q.name and q.locality:
            by_name = _name_path(q, entries, params, as_of)
            if by_name.outcome in (Result.FOUND, Result.DIFFERS):
                # The licence was not found, so "licence" becomes the first difference shown.
                diffs = ("licence", *(d for d in by_name.differences if d != "licence"))
                result = CheckResult(Result.DIFFERS, by_name.entries, diffs)
            else:
                result = by_name
    elif q.name and q.locality:
        result = _name_path(q, entries, params, as_of)
    return CheckResult(result.outcome, result.entries, result.differences, as_of)


def registry_summary() -> dict[str, int] | None:
    """Return real counts for the public statistics strip (D94).

    The counts are the entries and districts in the registry that tourists search. Returns
    None when no registry is loaded, so the page hides the strip.
    """
    try:
        batch = current_registry_batch()
    except RegistryUnavailable:
        return None
    rows = RegistryEntry.objects.filter(batch=batch)
    entries = rows.count()
    if not entries:
        return None
    return {"entries": entries, "districts": rows.values("district").distinct().count()}


def record(outcome: str) -> None:
    """Log a completed check: result type and timestamp only (AGENTS.md rule 5).

    Nothing else is stored. No query text, no client address and no session id, so the log
    cannot be used to find out who searched for what.
    """
    TouristCheck.objects.create(result=outcome)
