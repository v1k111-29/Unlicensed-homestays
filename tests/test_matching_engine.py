"""M4 matching engine (data-and-matching.md §5-7). Pure Python: no database needed.

Uses the committed DEV set only. The test set is never read here (AGENTS.md rule 9).
Ground truth is read by these tests to measure blocking recall; the engine never sees it.
"""

from __future__ import annotations

import ast
import builtins
import csv
import random
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from matching import engine
from matching.engine import (
    MATCHED_CONFIRMED,
    MATCHED_LICENCE,
    MATCHED_SCORE,
    NO_CANDIDATE,
    PRIORITY,
    REVIEW_LICENCE,
    REVIEW_SCORE,
    Candidate,
    assign_band,
    match,
)
from matching.features import (
    FEATURES,
    infer_category,
    licence_key,
    prepare_listing,
    weighted_score,
)
from matching.gazetteer import Gazetteer
from matching.params import PARAMS, get_params
from matching.records import (
    ListingRecord,
    RegistryRecord,
    listing_records_from_csv,
    registry_records_from_csv,
)

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "data" / "synthetic" / "out" / "dev"
AS_OF = date(2026, 4, 1)  # generator REFERENCE_DATE (M1)
PARAMS_V = get_params()
ENGINE_MODULES = ["engine", "features", "records", "params", "services"]


@pytest.fixture(scope="module")
def gaz() -> Gazetteer:
    return Gazetteer.load()


@pytest.fixture(scope="module")
def dev_registry() -> list[RegistryRecord]:
    return registry_records_from_csv(DEV / "registry.csv")


@pytest.fixture(scope="module")
def dev_listings() -> list[ListingRecord]:
    return listing_records_from_csv(DEV / "listings.csv")


@pytest.fixture(scope="module")
def dev_truth() -> dict[str, dict[str, str]]:
    with open(DEV / "ground_truth.csv", encoding="utf-8", newline="") as fh:
        return {r["listing_id"]: r for r in csv.DictReader(fh)}


@pytest.fixture(scope="module")
def dev_outcomes(dev_listings, dev_registry, gaz) -> list[engine.Outcome]:
    return match(dev_listings, dev_registry, PARAMS_V, as_of=AS_OF, gazetteer=gaz)


def _summary(outcomes: list[engine.Outcome]) -> list[tuple]:
    return [
        (
            o.listing_id,
            o.band,
            o.reasons,
            o.score,
            o.top_registry_id,
            [(c.registry_id, c.score, c.rank, c.blocked_by, c.features) for c in o.candidates],
        )
        for o in outcomes
    ]


# ------------------------------------------------------------------ determinism


def test_same_inputs_same_outputs(dev_listings, dev_registry, gaz, dev_outcomes) -> None:
    again = match(dev_listings, dev_registry, PARAMS_V, as_of=AS_OF, gazetteer=gaz)
    assert _summary(again) == _summary(dev_outcomes)


def test_input_order_does_not_change_outputs(dev_listings, dev_registry, gaz, dev_outcomes) -> None:
    rng = random.Random(7)
    listings, registry = list(dev_listings), list(dev_registry)
    rng.shuffle(listings)
    rng.shuffle(registry)
    shuffled = match(listings, registry, PARAMS_V, as_of=AS_OF, gazetteer=gaz)
    assert _summary(shuffled) == _summary(dev_outcomes)


def test_ties_are_broken_by_licence_number(gaz) -> None:
    twin = dict(
        name="Teak Arbour Homestay",
        district="Nilgiris",
        locality="Ooty",
        valid_to=date(2030, 1, 1),
        pincode="643001",
        category="homestay",
    )
    registry = [
        RegistryRecord(id="b", licence_no="SYN-B", **twin),
        RegistryRecord(id="a", licence_no="SYN-A", **twin),
    ]
    listing = ListingRecord(
        id=1,
        title="Teak Arbour Homestay",
        locality_text="Ooty",
        district="Nilgiris",
        pincode="643001",
    )
    (out,) = match([listing], registry, PARAMS_V, as_of=AS_OF, gazetteer=gaz)
    assert [c.licence_no for c in out.candidates] == ["SYN-A", "SYN-B"]
    assert out.candidates[0].score == out.candidates[1].score
    # Two equal candidates above T_high: several similar, so a human looks at it.
    assert out.band == REVIEW_SCORE
    assert out.reasons == ("several_similar",)


# --------------------------------------------------------------------- blocking


def test_blocking_recall_on_dev(dev_outcomes, dev_truth) -> None:
    with_truth = [o for o in dev_outcomes if dev_truth[o.listing_id]["true_registry_id"]]
    found = [
        o
        for o in with_truth
        if dev_truth[o.listing_id]["true_registry_id"] in {c.registry_id for c in o.candidates}
    ]
    assert len(with_truth) > 150
    assert len(found) / len(with_truth) >= 0.99


def test_blocking_is_not_all_pairs(dev_listings, dev_registry, gaz) -> None:
    by_district: dict[str, int] = {}
    for r in dev_registry:
        by_district[r.district] = by_district.get(r.district, 0) + 1
    all_pairs = sum(by_district[x.district] for x in dev_listings)
    # Count every blocked pair (no top-N cut).
    params = replace(PARAMS_V, max_stored_candidates=10_000)
    out = match(dev_listings, dev_registry, params, as_of=AS_OF, gazetteer=gaz)
    blocked = sum(len(o.candidates) for o in out)
    assert blocked < 0.5 * all_pairs


def test_blocking_rules_are_recorded(dev_outcomes) -> None:
    rules = {"licence", "pincode", "locality", "radius", "name_key", "confirmed"}
    for o in dev_outcomes:
        for c in o.candidates:
            assert c.blocked_by and set(c.blocked_by) <= rules


def test_licence_hit_is_always_a_candidate(gaz) -> None:
    far = RegistryRecord(
        id=1,
        licence_no="SYN-NLG-00001-A",
        name="Quartz Hollow Lodge",
        district="Nilgiris",
        locality="Gudalur",
        valid_to=date(2030, 1, 1),
        pincode="643212",
        lat=11.503,
        lng=76.493,
    )
    listing = ListingRecord(
        id=1,
        title="Something Else Entirely",
        locality_text="Ooty",
        district="Nilgiris",
        pincode="643001",
        lat=11.41,
        lng=76.695,
        claimed_licence_no="syn nlg 00001 a",
    )
    (out,) = match([listing], [far], PARAMS_V, as_of=AS_OF, gazetteer=gaz)
    assert out.candidates[0].blocked_by == ("licence",)
    assert out.band == REVIEW_LICENCE  # licence found, but name and place disagree


# ---------------------------------------------------------------- district isolation


def test_no_candidate_from_another_district(gaz) -> None:
    same = dict(
        name="Teak Arbour Homestay",
        locality="Ooty",
        valid_to=date(2030, 1, 1),
        pincode="643001",
        lat=11.41,
        lng=76.695,
        category="homestay",
    )
    other = RegistryRecord(id="cbe", licence_no="SYN-X-1", district="Coimbatore", **same)
    listing = ListingRecord(
        id=1,
        title="Teak Arbour Homestay",
        locality_text="Ooty",
        district="Nilgiris",
        pincode="643001",
        lat=11.41,
        lng=76.695,
        claimed_licence_no="SYN-X-1",
    )
    (out,) = match([listing], [other], PARAMS_V, as_of=AS_OF, gazetteer=gaz)
    assert out.candidates == ()
    assert out.band == REVIEW_LICENCE
    assert out.reasons == ("licence_not_in_registry",)


def test_dev_candidates_stay_in_district(dev_outcomes, dev_listings, dev_registry) -> None:
    listing_district = {x.id: x.district for x in dev_listings}
    registry_district = {r.id: r.district for r in dev_registry}
    for o in dev_outcomes:
        for c in o.candidates:
            assert registry_district[c.registry_id] == listing_district[o.listing_id]


# ---------------------------------------------------------------- features


def test_features_are_stored_per_pair(dev_outcomes) -> None:
    n = 0
    for o in dev_outcomes:
        for c in o.candidates:
            n += 1
            for name in FEATURES:
                value = c.features[name]
                assert value is None or 0.0 <= value <= 1.0, (name, value)
            assert c.features["name"] is not None
            detail = c.features["detail"]
            assert {"licence_status", "name", "address_method", "distance_km"} <= set(detail)
            assert c.score == weighted_score(c.features, PARAMS_V)
    assert n > 0


def test_missing_features_are_left_out_of_the_score() -> None:
    feats = {
        "licence": None,
        "name": 1.0,
        "address": 1.0,
        "distance": None,
        "pincode": None,
        "category": None,
    }
    assert weighted_score(feats, PARAMS_V) == 1.0
    feats["pincode"] = 0.0
    w = PARAMS_V.weights
    expected = round((w.name + w.address) / (w.name + w.address + w.pincode), 4)
    assert weighted_score(feats, PARAMS_V) == expected


def test_licence_key_ignores_case_and_punctuation() -> None:
    assert licence_key(" syn-nlg 49713/b ") == licence_key("SYN-NLG-49713-B")
    assert licence_key("") == ""


@pytest.mark.parametrize(
    ("title", "category"),
    [
        ("Clover Loft Inn", "lodge"),
        ("Amber Court Cottage", "cottage"),
        ("Teak Guest House", "guest_house"),
        ("Teak GH", "guest_house"),
        ("Coral Nook H/Stay", "homestay"),
        ("Kingfisher Arbour Stay", None),
    ],
)
def test_category_inferred_from_title(title, category, gaz) -> None:
    rec = ListingRecord(id=1, title=title, locality_text="Ooty", district="Nilgiris")
    assert prepare_listing(rec, gaz, PARAMS_V).category == category
    assert infer_category(()) is None


# ------------------------------------------------------------------- bands


def _cand(score: float, name: float = 1.0, rank: int = 1, **feats) -> Candidate:
    features = {
        "licence": None,
        "name": name,
        "address": 1.0,
        "distance": None,
        "pincode": 1.0,
        "category": None,
        "detail": {"address_method": "same_locality", "distance_km": None},
    }
    features.update(feats)
    return Candidate(
        registry_id=rank,
        licence_no=f"L{rank}",
        score=score,
        rank=rank,
        blocked_by=("pincode",),
        features=features,
    )


@pytest.fixture()
def plain_listing(gaz):
    rec = ListingRecord(id=1, title="Teak Arbour", locality_text="Ooty", district="Nilgiris")
    return prepare_listing(rec, gaz, PARAMS_V)


@pytest.fixture()
def licensed_listing(gaz):
    rec = ListingRecord(
        id=1,
        title="Teak Arbour",
        locality_text="Ooty",
        district="Nilgiris",
        claimed_licence_no="SYN-1",
    )
    return prepare_listing(rec, gaz, PARAMS_V)


def _band(lst, cands, **kw):
    kw.setdefault("licence_hit", None)
    kw.setdefault("licence_hit_valid", False)
    return assign_band(lst, cands, PARAMS_V, **kw)


def test_band_boundaries_score_path(plain_listing) -> None:
    p = PARAMS_V
    assert _band(plain_listing, [_cand(p.t_high)])[0] == MATCHED_SCORE
    assert _band(plain_listing, [_cand(round(p.t_high - 0.0001, 4))])[0] == REVIEW_SCORE
    assert _band(plain_listing, [_cand(p.t_low)])[0] == REVIEW_SCORE
    assert _band(plain_listing, [_cand(round(p.t_low - 0.0001, 4))])[0] == NO_CANDIDATE
    assert _band(plain_listing, [])[0] == NO_CANDIDATE
    band, reasons, top = _band(plain_listing, [_cand(0.1)])
    assert (band, reasons, top) == (NO_CANDIDATE, ("no_candidate_above_t_low",), None)


def test_band_ambiguity_margin(plain_listing) -> None:
    p = PARAMS_V
    first = _cand(1.0)
    close = _cand(round(1.0 - p.ambiguity_margin + 0.0001, 4), rank=2)
    clear = _cand(round(1.0 - p.ambiguity_margin, 4), rank=2)
    assert _band(plain_listing, [first, close])[:2] == (REVIEW_SCORE, ("several_similar",))
    assert _band(plain_listing, [first, clear])[0] == MATCHED_SCORE


def test_band_name_gate(plain_listing) -> None:
    p = PARAMS_V
    assert _band(plain_listing, [_cand(0.95, name=p.score_name_min)])[0] == MATCHED_SCORE
    low = round(p.score_name_min - 0.0001, 4)
    assert _band(plain_listing, [_cand(0.95, name=low)])[:2] == (REVIEW_SCORE, ("name_differs",))


def test_band_licence_paths(licensed_listing) -> None:
    hit = _cand(0.9, licence=1.0)
    assert _band(licensed_listing, [hit], licence_hit=hit, licence_hit_valid=True)[:2] == (
        MATCHED_LICENCE,
        ("licence_valid_details_consistent",),
    )
    # Claimed licence not in the registry (missing / malformed / other district).
    assert _band(licensed_listing, [_cand(0.99)])[:2] == (
        REVIEW_LICENCE,
        ("licence_not_in_registry",),
    )
    # Expired or suspended.
    lapsed = _cand(0.9, licence=0.5)
    assert _band(licensed_listing, [lapsed], licence_hit=lapsed)[:2] == (
        REVIEW_LICENCE,
        ("licence_not_valid",),
    )
    # Valid licence but the name belongs to another stay.
    other = _cand(0.9, name=round(PARAMS_V.licence_name_min - 0.0001, 4), licence=1.0)
    out = _band(licensed_listing, [other], licence_hit=other, licence_hit_valid=True)
    assert out[:2] == (REVIEW_LICENCE, ("licence_name_differs",))
    # Valid licence, right name, wrong place.
    away = _cand(
        0.9,
        licence=1.0,
        address=0.2,
        pincode=0.0,
        distance=0.01,
        detail={"address_method": "text", "distance_km": 9.0},
    )
    out = _band(licensed_listing, [away], licence_hit=away, licence_hit_valid=True)
    assert out[:2] == (REVIEW_LICENCE, ("licence_locality_differs",))


def test_band_confirmed_pair(plain_listing) -> None:
    c = _cand(0.3)
    assert _band(plain_listing, [c], confirmed=c)[0] == MATCHED_CONFIRMED
    out = _band(plain_listing, [c], confirmed=c, confirmed_valid=False)
    assert out[:2] == (REVIEW_LICENCE, ("confirmed_entry_not_valid",))


def test_confirmed_pair_is_not_flagged_again(gaz) -> None:
    entry = RegistryRecord(
        id=5,
        licence_no="SYN-5",
        name="Quartz Hollow Lodge",
        district="Nilgiris",
        locality="Gudalur",
        valid_to=date(2030, 1, 1),
    )
    listing = ListingRecord(id=9, title="Hilltop Rooms", locality_text="Ooty", district="Nilgiris")
    (before,) = match([listing], [entry], PARAMS_V, as_of=AS_OF, gazetteer=gaz)
    assert before.band == NO_CANDIDATE
    (after,) = match([listing], [entry], PARAMS_V, as_of=AS_OF, gazetteer=gaz, confirmed={9: [5]})
    assert after.band == MATCHED_CONFIRMED
    assert after.top_registry_id == 5


def test_queue_priority_order() -> None:
    # Licence issue -> no candidate -> ambiguous (§7); matched bands after the queue.
    assert PRIORITY[REVIEW_LICENCE] < PRIORITY[NO_CANDIDATE] < PRIORITY[REVIEW_SCORE]
    assert PRIORITY[REVIEW_SCORE] < min(
        PRIORITY[MATCHED_SCORE], PRIORITY[MATCHED_LICENCE], PRIORITY[MATCHED_CONFIRMED]
    )
    assert set(engine.STATUS.values()) == {"matched", "needs_review", "no_match"}


def test_validity_is_judged_on_as_of(gaz) -> None:
    entry = RegistryRecord(
        id=1,
        licence_no="SYN-1",
        name="Teak Arbour Homestay",
        district="Nilgiris",
        locality="Ooty",
        valid_to=date(2026, 5, 1),
        pincode="643001",
    )
    listing = ListingRecord(
        id=1,
        title="Teak Arbour Homestay",
        locality_text="Ooty",
        district="Nilgiris",
        pincode="643001",
        claimed_licence_no="SYN-1",
    )
    (inside,) = match([listing], [entry], PARAMS_V, as_of=date(2026, 4, 1), gazetteer=gaz)
    (after,) = match([listing], [entry], PARAMS_V, as_of=date(2026, 6, 1), gazetteer=gaz)
    assert inside.band == MATCHED_LICENCE
    assert after.band == REVIEW_LICENCE
    assert after.reasons == ("licence_not_valid",)


# ------------------------------------------------------------ dev sanity [synthetic]


def test_dev_bands_sanity(dev_outcomes, dev_truth) -> None:
    """Coarse sanity on DEV only; M5 owns the real metrics. Synthetic results say nothing
    about real-world accuracy (AGENTS.md rule 10)."""
    wrong = [
        o.listing_id
        for o in dev_outcomes
        if o.status == "matched"
        and o.top_registry_id != (dev_truth[o.listing_id]["true_registry_id"] or None)
    ]
    assert wrong == []
    lapsed = [o for o in dev_outcomes if dev_truth[o.listing_id]["type"] == "wrong_or_expired"]
    assert lapsed and all(o.band == REVIEW_LICENCE for o in lapsed)
    no_cp = [o for o in dev_outcomes if dev_truth[o.listing_id]["type"] == "no_counterpart"]
    assert all(o.status != "matched" for o in no_cp)


# ------------------------------------------------------------ ground truth


def _non_docstring_strings_and_names(tree: ast.AST) -> list[str]:
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                out.append(node.value)
        elif isinstance(node, ast.Name):
            out.append(node.id)
        elif isinstance(node, ast.Attribute):
            out.append(node.attr)
        elif isinstance(node, ast.alias):
            out.append(node.name)
    return out


@pytest.mark.parametrize("module", ENGINE_MODULES)
def test_matcher_code_never_mentions_ground_truth(module: str) -> None:
    src = (ROOT / "src" / "matching" / f"{module}.py").read_text(encoding="utf-8")
    words = _non_docstring_strings_and_names(ast.parse(src))
    bad = [w for w in words if "groundtruth" in w.lower().replace("_", "")]
    assert bad == []


def test_matcher_never_opens_ground_truth(monkeypatch, dev_listings, dev_registry) -> None:
    real_open = builtins.open
    opened: list[str] = []

    def guarded(file, *args, **kwargs):
        opened.append(str(file))
        if "ground_truth" in str(file):
            raise AssertionError(f"matcher opened {file}")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded)
    out = match(dev_listings, dev_registry, PARAMS_V, as_of=AS_OF, gazetteer=Gazetteer.load())
    assert len(out) == len(dev_listings)
    assert opened  # the gazetteer files were read through the guard


@pytest.mark.parametrize("module", ["engine", "features", "records", "params"])
def test_engine_modules_do_not_import_django(module: str) -> None:
    tree = ast.parse((ROOT / "src" / "matching" / f"{module}.py").read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not any(m.split(".")[0] == "django" for m in imported)


# ------------------------------------------------------------------ params


def test_params_versions_are_pinned() -> None:
    """Changing the values of a published version must fail: add a new version instead."""
    for version, params in PARAMS.items():
        assert params.version == version
        assert version in PINNED_FINGERPRINTS, f"pin the fingerprint of {version}"
        assert params.fingerprint() == PINNED_FINGERPRINTS[version]
    w = PARAMS_V.weights
    assert round(w.licence + w.name + w.address + w.distance + w.pincode + w.category, 6) == 1.0
    assert PARAMS_V.t_low < PARAMS_V.t_high


def test_unknown_params_version() -> None:
    with pytest.raises(KeyError):
        get_params("nope")


PINNED_FINGERPRINTS = {"m4-initial-1": "83bd9f5d189fc545"}
