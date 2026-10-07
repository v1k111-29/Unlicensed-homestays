"""Tests for matching.gazetteer: loading and (district, alias) resolution, Tamil and English."""

import csv
from pathlib import Path

import pytest

from matching.gazetteer import DEFAULT_GAZETTEER, Gazetteer, GazetteerError, Locality
from matching.normalise import normalise_address


@pytest.fixture(scope="module")
def gz() -> Gazetteer:
    return Gazetteer.load()


def test_loads_all_districts_and_localities(gz: Gazetteer) -> None:
    assert len(gz.districts) == 8
    assert "Nilgiris" in gz.districts
    ooty = gz.locality("nilgiris", "OOTY")
    assert ooty is not None and ooty.pincode == "643001"


def test_every_gazetteer_alias_resolves_exactly_to_its_locality(gz: Gazetteer) -> None:
    with open(DEFAULT_GAZETTEER, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows
    for row in rows:
        res = gz.resolve(row["district"], row["alias"])
        assert res is not None, row
        assert (res.locality, res.method) == (row["locality"], "exact"), row


@pytest.mark.parametrize(
    ("district", "text", "locality"),
    [
        # Tamil / English aliases of the same place resolve to one canonical locality.
        ("Nilgiris", "Udhagamandalam", "Ooty"),
        ("Nilgiris", "ஊட்டி", "Ooty"),
        ("Nilgiris", "உதகமண்டலம்", "Ooty"),
        ("Nilgiris", "உதகை", "Ooty"),
        ("Nilgiris", "குன்னூர்", "Coonoor"),
        ("Coimbatore", "R.S. Puram", "RS Puram"),
        ("Coimbatore", "ஆர்.எஸ். புரம்", "RS Puram"),
        ("Chennai", "தி. நகர்", "T Nagar"),
        ("Chennai", "Thyagaraya Ngr", "T Nagar"),
        ("Thanjavur", "Tanjore", "Thanjavur Town"),
        ("Thanjavur", "தஞ்சை", "Thanjavur Town"),
    ],
)
def test_tamil_english_alias_resolution(
    gz: Gazetteer, district: str, text: str, locality: str
) -> None:
    res = gz.resolve(district, text)
    assert res is not None
    assert res.locality == locality
    assert res.district == district


def test_contains_and_phonetic_tiers(gz: Gazetteer) -> None:
    assert gz.resolve("Nilgiris", "Near Ooty bus stand").method == "contains"
    assert gz.resolve("Dindigul", "Dindigul Tn").locality == "Dindigul Town"
    assert gz.resolve("Ramanathapuram", "Ramanathapuram Tn").locality == "Ramanathapuram Town"
    res = gz.resolve("Nilgiris", "Kothagiri")
    assert (res.locality, res.method) == ("Kotagiri", "phonetic")
    assert gz.resolve("Nilgiris", "Love Dale").locality == "Lovedale"


def test_never_resolves_across_districts(gz: Gazetteer) -> None:
    assert gz.resolve("Chennai", "Ooty") is None
    assert gz.resolve("Nilgiris", "Kodaikanal") is None
    assert gz.resolve("Unknown district", "Ooty") is None


def test_same_alias_in_two_districts_stays_separate() -> None:
    locs = [
        Locality("A", "Anna Nagar", "600040", 13.0, 80.0),
        Locality("B", "Anna Nagar", "625020", 9.9, 78.1),
    ]
    g = Gazetteer(locs, [("A", "AN", "Anna Nagar"), ("B", "AN", "Anna Nagar")])
    assert g.resolve("A", "AN").district == "A"
    assert g.resolve("B", "AN").district == "B"


def test_district_phrase_and_unknown_text_do_not_resolve(gz: Gazetteer) -> None:
    assert gz.resolve("Dindigul", "Dindigul district") is None
    assert gz.resolve("Nilgiris", "Nilgiris district") is None
    assert gz.resolve("Nilgiris", "Ooty, Nilgiris District").locality == "Ooty"
    assert gz.resolve("Nilgiris", "somewhere else") is None
    assert gz.resolve("Nilgiris", "") is None


def test_ambiguous_text_returns_none(gz: Gazetteer) -> None:
    assert gz.resolve("Nilgiris", "Ooty or Coonoor") is None


def test_canonicalise_replaces_aliases_in_address(gz: Gazetteer) -> None:
    en = normalise_address("3, Lake Rd, Udhagamandalam", "Nilgiris", gz)
    ta = normalise_address("3, லேக் ரோடு, ஊட்டி", "Nilgiris", gz)
    assert en.tokens == ("3", "lake", "road", "ooty")
    assert ta.tokens[-2:] == ("road", "ooty")


def test_localities_for_pincode(gz: Gazetteer) -> None:
    assert gz.localities_for_pincode("Nilgiris", "643001") == ["Ooty"]
    assert gz.localities_for_pincode("Chennai", "643001") == []


def test_inconsistent_files_raise(tmp_path: Path) -> None:
    locs = [Locality("A", "X", "600001", 13.0, 80.0), Locality("A", "Y", "600002", 13.0, 80.0)]
    with pytest.raises(GazetteerError):
        Gazetteer(locs, [("A", "Z alias", "Z")])  # unknown locality
    with pytest.raises(GazetteerError):
        Gazetteer(locs, [("A", "Same", "X"), ("A", "same", "Y")])  # clashing alias
