"""Unit tests for matching.normalise: one group per step of data-and-matching.md §4."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from matching.normalise import (
    basic_clean,
    expand_abbreviations,
    extract_pincode,
    has_tamil,
    is_generic,
    normalise_address,
    normalise_name,
    phonetic_key,
    remove_generic_words,
    remove_stopwords,
    tamil_to_latin,
    tamil_token_to_latin,
)

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- step 1: clean


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Clover   LOFT  Inn ", "clover loft inn"),
        ("Hill Rd., Ooty-1", "hill rd ooty 1"),
        ("St. Mary's Homestay", "st marys homestay"),
        ("R.S. Puram", "rs puram"),
        ("R S Puram", "rs puram"),
        ("T Nagar", "t nagar"),
        ("H/Stay", "h stay"),
        ("Amber & Court", "amber court"),
        ("", ""),
    ],
)
def test_basic_clean(raw: str, expected: str) -> None:
    assert basic_clean(raw) == expected


def test_basic_clean_nfc_and_casefold() -> None:
    decomposed = "Café"  # e + combining acute
    assert basic_clean(decomposed) == "café"
    assert basic_clean("STRASSE") == basic_clean("strasse")


def test_basic_clean_keeps_tamil_vowel_signs() -> None:
    # Tamil vowel signs and the virama are combining marks; they must survive.
    assert basic_clean("கோத்தகிரி") == "கோத்தகிரி"
    assert basic_clean("ஆர்.எஸ். புரம்") == "ஆர் எஸ் புரம்"


# ------------------------------------------------------------ step 2: abbreviations


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (["hill", "rd"], ["hill", "road"]),
        (["bazaar", "st"], ["bazaar", "street"]),
        (["anna", "ngr"], ["anna", "nagar"]),
        (["amber", "ctg"], ["amber", "cottage"]),
        (["sandal", "haven", "gh"], ["sandal", "haven", "guest", "house"]),
        (["plum", "knoll", "h", "stay"], ["plum", "knoll", "homestay"]),
        (["maple", "home", "stay"], ["maple", "homestay"]),
        (["peacock", "ct"], ["peacock", "court"]),
        (["clover", "loft"], ["clover", "loft"]),
    ],
)
def test_expand_abbreviations(tokens: list[str], expected: list[str]) -> None:
    assert expand_abbreviations(tokens) == expected


# ---------------------------------------------------------------- step 4: Tamil


def test_has_tamil() -> None:
    assert has_tamil("ஊட்டி")
    assert not has_tamil("Ooty")


def test_tamil_lexicon_words_map_to_english() -> None:
    assert tamil_to_latin(["ஹோம்ஸ்டே", "லாட்ஜ்", "ரோடு", "தெரு"]) == [
        "homestay",
        "lodge",
        "road",
        "street",
    ]


@pytest.mark.parametrize(
    ("tamil", "latin_key"),
    [
        ("ஊட்டி", "uti"),  # Ooty
        ("குன்னூர்", "kunur"),  # Coonoor
        ("கோத்தகிரி", "kotakiri"),  # Kotagiri
        ("மசினகுடி", "masinakuti"),  # Masinagudi
        ("பழனி", "palani"),  # Palani
    ],
)
def test_tamil_transliteration_matches_english_key(tamil: str, latin_key: str) -> None:
    latin = tamil_token_to_latin(tamil)
    assert latin.isascii() and latin.isalpha()
    assert phonetic_key(latin) == latin_key


def test_tamil_to_latin_passes_latin_through() -> None:
    assert tamil_to_latin(["ooty", "643001"]) == ["ooty", "643001"]


# ------------------------------------------------------------- step 5: pincode


@pytest.mark.parametrize(
    ("raw", "pincode"),
    [
        ("12, Lake Road, Ooty 643001", "643001"),
        ("Ooty - 643 001", "643001"),
        ("no pincode here", None),
        ("phone 9876543210", None),  # 10 digits is not a pincode
        ("012345", None),  # pincodes never start with 0
    ],
)
def test_extract_pincode(raw: str, pincode: str | None) -> None:
    found, rest = extract_pincode(raw)
    assert found == pincode
    if pincode:
        assert pincode[:3] not in rest


# ---------------------------------------------------- step 6: stopwords, generics


def test_remove_stopwords() -> None:
    assert remove_stopwords(["the", "amber", "and", "court"]) == ["amber", "court"]


@pytest.mark.parametrize(
    "word", ["homestay", "villa", "cottage", "resort", "inn", "lodge", "residency", "house"]
)
def test_generic_words(word: str) -> None:
    assert is_generic(word)


def test_generic_words_tolerate_one_typo_on_long_words_only() -> None:
    assert is_generic("cotage")
    assert is_generic("hmestay")
    assert is_generic("residncy")
    assert not is_generic("horse")  # one edit from "house", but short words are exact only
    assert not is_generic("clover")


def test_remove_generic_words_keeps_something() -> None:
    assert remove_generic_words(["clover", "loft", "inn"]) == ["clover", "loft"]
    assert remove_generic_words(["guest", "house"]) == ["guest", "house"]


# ------------------------------------------------------------- phonetic key


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("kotagiri", "kothagiri"),
        ("coonoor", "kunnur"),
        ("palani", "pazhani"),
        ("mylapore", "mylapor"),
        ("teak", "tik"),
        ("hollow", "hollo"),
    ],
)
def test_phonetic_key_equal(a: str, b: str) -> None:
    assert phonetic_key(a) == phonetic_key(b)


@pytest.mark.parametrize(("a", "b"), [("clover", "maple"), ("ooty", "coonoor")])
def test_phonetic_key_different(a: str, b: str) -> None:
    assert phonetic_key(a) != phonetic_key(b)


def test_phonetic_key_leaves_non_ascii() -> None:
    assert phonetic_key("ஊட்டி") == "ஊட்டி"


# ------------------------------------------------------------------ pipeline


def test_normalise_name_pipeline() -> None:
    n = normalise_name("The Clover Loft H/Stay")
    assert n.tokens == ("clover", "loft", "homestay")
    assert n.core_tokens == ("clover", "loft")
    assert n.core == "clover loft"
    assert n.compact == "cloverloft"
    assert n.pincode is None


def test_normalise_name_tamil_title() -> None:
    n = normalise_name("க்லோவேர் லோஃப்ட் இன்")  # "Clover Loft Inn" in Tamil script
    assert n.keys == normalise_name("Clover Loft Inn").keys


def test_normalise_address_keeps_generic_and_extracts_pincode() -> None:
    n = normalise_address("12, Cottage Rd, Ooty 643001")
    assert n.tokens == ("12", "cottage", "road", "ooty")
    assert n.pincode == "643001"


def test_reordered_and_abbreviated_names_share_core_tokens() -> None:
    a = normalise_name("Homestay Peacock Ct")
    b = normalise_name("Peacock Court Homestay")
    assert sorted(a.core_tokens) == sorted(b.core_tokens)


def test_deterministic() -> None:
    texts = ["Clover Loft Inn", "கோத்தகிரி ஹோம்ஸ்டே", "12, Hill Rd, Ooty 643001"]
    assert [normalise_name(t) for t in texts] == [normalise_name(t) for t in texts]


def test_matching_core_does_not_import_django() -> None:
    code = (
        "import sys; import matching.normalise, matching.gazetteer; "
        "sys.exit(1 if 'django' in sys.modules else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
