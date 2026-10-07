"""Normaliser checks against the committed M1 DEV set (data/synthetic/out/dev).

Only the dev set is used here. The test set is never read for tuning (AGENTS.md rule 9).
These are sanity checks on synthetic data; they say nothing about real-world accuracy.
"""

import csv
import os
import subprocess
import sys
from pathlib import Path

import pytest
from rapidfuzz import fuzz

from data.synthetic import generator as gen
from matching.gazetteer import Gazetteer
from matching.normalise import normalise_address, normalise_name

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "data" / "synthetic" / "out" / "dev"


def _read(name: str) -> list[dict[str, str]]:
    with open(DEV / name, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def gz() -> Gazetteer:
    return Gazetteer.load()


@pytest.fixture(scope="module")
def dev() -> dict[str, object]:
    registry = {r["licence_no"]: r for r in _read("registry.csv")}
    listings = {r["listing_id"]: r for r in _read("listings.csv")}
    truth = _read("ground_truth.csv")
    return {"registry": registry, "listings": listings, "truth": truth}


def _pairs(dev: dict, types: tuple[str, ...]) -> list[tuple[dict, dict, dict]]:
    out = []
    for row in dev["truth"]:
        if row["type"] in types and row["true_registry_id"]:
            out.append(
                (row, dev["listings"][row["listing_id"]], dev["registry"][row["true_registry_id"]])
            )
    return out


def test_every_dev_listing_locality_resolves_in_its_district(gz: Gazetteer, dev: dict) -> None:
    for listing in dev["listings"].values():
        res = gz.resolve(listing["district"], listing["locality_text"])
        assert res is not None, listing["locality_text"]


def test_listing_locality_resolves_to_registry_locality(gz: Gazetteer, dev: dict) -> None:
    pairs = _pairs(dev, ("clean", "noisy", "wrong_or_expired"))
    assert len(pairs) > 100
    for _, listing, reg in pairs:
        res = gz.resolve(listing["district"], listing["locality_text"])
        assert res is not None and res.locality == reg["locality"], listing["locality_text"]


def test_clean_listings_normalise_to_registry_name(dev: dict) -> None:
    for _, listing, reg in _pairs(dev, ("clean",)):
        assert normalise_name(listing["title"]).core == normalise_name(reg["name"]).core


def test_abbreviation_and_reorder_noise_is_fully_undone(dev: dict) -> None:
    pairs = [p for p in _pairs(dev, ("noisy",)) if "typo" not in p[0]["noise"]]
    assert len(pairs) > 30
    for _, listing, reg in pairs:
        a, b = normalise_name(listing["title"]), normalise_name(reg["name"])
        assert sorted(a.core_tokens) == sorted(b.core_tokens), (listing["title"], reg["name"])


def test_typo_noise_stays_close_and_normalisation_helps(dev: dict) -> None:
    pairs = [p for p in _pairs(dev, ("noisy",)) if "typo" in p[0]["noise"]]
    assert len(pairs) > 30
    raw, norm = [], []
    for _, listing, reg in pairs:
        raw.append(fuzz.token_set_ratio(listing["title"], reg["name"]))
        score = fuzz.token_set_ratio(
            normalise_name(listing["title"]).core, normalise_name(reg["name"]).core
        )
        norm.append(score)
        assert score >= 85, (listing["title"], reg["name"], score)
    assert sum(norm) / len(norm) > sum(raw) / len(raw)


def test_registry_cores_stay_distinct_within_district(dev: dict) -> None:
    """Normalisation must not merge two different properties (hard negatives need this)."""
    seen: dict[tuple[str, tuple[str, ...]], str] = {}
    for reg in dev["registry"].values():
        key = (reg["district"], tuple(sorted(normalise_name(reg["name"]).core_tokens)))
        assert key not in seen, (reg["name"], seen.get(key))
        seen[key] = reg["name"]


def test_hard_negatives_do_not_normalise_to_a_registry_name(dev: dict) -> None:
    cores = {(r["district"], normalise_name(r["name"]).core) for r in dev["registry"].values()}
    hard = [r for r in dev["truth"] if r["type"] == "hard_negative"]
    assert hard
    for row in hard:
        listing = dev["listings"][row["listing_id"]]
        assert (listing["district"], normalise_name(listing["title"]).core) not in cores


def test_tamil_address_matches_english_address(gz: Gazetteer, dev: dict) -> None:
    """address_ta (Tamil street + Tamil locality alias) canonicalises to the same locality."""
    checked = 0
    for reg in dev["registry"].values():
        if not reg["address_ta"]:
            continue
        ta = normalise_address(reg["address_ta"], reg["district"], gz)
        en = normalise_address(reg["address_en"], reg["district"], gz)
        locality_tokens = tuple(normalise_address(reg["locality"]).tokens)
        assert ta.tokens[-len(locality_tokens) :] == locality_tokens, reg["address_ta"]
        assert fuzz.token_set_ratio(ta.text, en.text) >= 70, (ta.text, en.text)
        checked += 1
    assert checked > 50


def test_tamil_script_names_round_trip_to_same_keys(dev: dict) -> None:
    """Registry names rendered in Tamil script (the generator's own rendering) normalise back
    to the same phonetic keys. Partly circular (D37): same library both ways."""
    names = [r["name"] for r in dev["registry"].values()]
    equal = 0
    for name in names:
        tamil = " ".join(gen._to_tamil(w) for w in name.split())
        a, b = normalise_name(tamil), normalise_name(name)
        if a.keys == b.keys:
            equal += 1
        assert fuzz.ratio(" ".join(a.keys), " ".join(b.keys)) >= 75, (name, a.keys, b.keys)
    assert equal / len(names) >= 0.85


def test_resolution_independent_of_hash_seed() -> None:
    code = (
        "import csv; from matching.gazetteer import Gazetteer; g = Gazetteer.load(); "
        f"rows = list(csv.DictReader(open(r'{DEV / 'listings.csv'}', encoding='utf-8'))); "
        "print([(g.resolve(r['district'], r['locality_text']) or (None,)) for r in rows])"
    )
    outputs = set()
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT / "src")}
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        outputs.add(result.stdout)
    assert len(outputs) == 1
