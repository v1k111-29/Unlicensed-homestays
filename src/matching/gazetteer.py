"""Locality gazetteer: alias resolution keyed by ``(district, alias)``. Pure Python, no Django.

Loads ``data/synthetic/localities.csv`` (canonical localities) and
``data/synthetic/gazetteer.csv`` (English and Tamil aliases). An alias is only ever
resolved inside the district it is listed under (data-and-matching.md §4 step 3).

Resolution order (``Gazetteer.resolve``), first hit wins:

1. ``exact``    cleaned text equals a cleaned alias or canonical name.
2. ``contains`` the text contains alias token sequences that all point to ONE locality
                ("Near Ooty bus stand", "Dindigul Tn").
3. ``phonetic`` the phonetic key of the whole text (spaces removed) equals that of
                exactly one locality's alias ("Kothagiri", "Love Dale").

Anything ambiguous returns ``None``; the matcher must then fall back to pincode/distance.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from matching.normalise import (
    basic_clean,
    expand_abbreviations,
    phonetic_key,
    tamil_to_latin,
)

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "synthetic"
DEFAULT_GAZETTEER = DATA_DIR / "gazetteer.csv"
DEFAULT_LOCALITIES = DATA_DIR / "localities.csv"

Method = Literal["exact", "contains", "phonetic"]


class GazetteerError(ValueError):
    """The gazetteer files are inconsistent (unknown locality, clashing alias, ...)."""


@dataclass(frozen=True)
class Locality:
    district: str
    name: str
    pincode: str
    lat: float
    lng: float


@dataclass(frozen=True)
class Resolution:
    district: str
    locality: str
    method: Method


def _district_key(district: str) -> str:
    return basic_clean(district)


def _alias_tokens(alias: str) -> tuple[str, ...]:
    return tuple(expand_abbreviations(basic_clean(alias).split()))


_DISTRICT_WORDS = frozenset({"district", "dist", "dt"})


def _drop_district_phrase(dk: str, tokens: list[str]) -> list[str]:
    """Remove "<district name> district" so "Dindigul district" does not resolve to the
    town alias "Dindigul". A bare district word on its own is dropped too."""
    name = dk.split()
    out: list[str] = []
    i = 0
    while i < len(tokens):
        n = len(name)
        if tokens[i : i + n] == name and i + n < len(tokens) and tokens[i + n] in _DISTRICT_WORDS:
            i += n + 1
        elif tokens[i] in _DISTRICT_WORDS:
            i += 1
        else:
            out.append(tokens[i])
            i += 1
    return out


def _sound(tokens: list[str] | tuple[str, ...]) -> str:
    """Phonetic key of a whole phrase, spaces removed (so "love dale" == "lovedale")."""
    return phonetic_key("".join(tamil_to_latin(list(tokens))))


class Gazetteer:
    def __init__(self, localities: list[Locality], aliases: list[tuple[str, str, str]]) -> None:
        """``aliases`` are ``(district, alias, canonical locality)`` triples."""
        self._districts: dict[str, str] = {}
        self._localities: dict[tuple[str, str], Locality] = {}
        self._by_pincode: dict[tuple[str, str], list[str]] = defaultdict(list)
        # district key -> alias tokens -> canonical locality name
        self._aliases: dict[str, dict[tuple[str, ...], str]] = defaultdict(dict)
        # district key -> phonetic key -> set of canonical names
        self._sounds: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        self._max_len = 1

        for loc in localities:
            dk = _district_key(loc.district)
            self._districts[dk] = loc.district
            lk = (dk, basic_clean(loc.name))
            if lk in self._localities:
                raise GazetteerError(f"duplicate locality {loc.district}/{loc.name}")
            self._localities[lk] = loc
            self._by_pincode[(dk, loc.pincode)].append(loc.name)
            self._add_alias(dk, loc.name, loc.name)

        for district, alias, locality in aliases:
            dk = _district_key(district)
            if (dk, basic_clean(locality)) not in self._localities:
                raise GazetteerError(f"alias {alias!r} points to unknown {district}/{locality}")
            self._add_alias(dk, alias, self._localities[(dk, basic_clean(locality))].name)

    def _add_alias(self, dk: str, alias: str, canonical: str) -> None:
        tokens = _alias_tokens(alias)
        if not tokens:
            raise GazetteerError(f"empty alias for {canonical}")
        existing = self._aliases[dk].get(tokens)
        if existing is not None and existing != canonical:
            raise GazetteerError(f"alias {alias!r} maps to both {existing} and {canonical}")
        self._aliases[dk][tokens] = canonical
        self._sounds[dk][_sound(tokens)].add(canonical)
        self._max_len = max(self._max_len, len(tokens))

    # ------------------------------------------------------------- loading

    @classmethod
    def load(
        cls,
        gazetteer_csv: Path | str = DEFAULT_GAZETTEER,
        localities_csv: Path | str = DEFAULT_LOCALITIES,
    ) -> Gazetteer:
        with open(localities_csv, encoding="utf-8", newline="") as fh:
            localities = [
                Locality(
                    district=row["district"].strip(),
                    name=row["locality"].strip(),
                    pincode=row["pincode"].strip(),
                    lat=float(row["lat"]),
                    lng=float(row["lng"]),
                )
                for row in csv.DictReader(fh)
            ]
        with open(gazetteer_csv, encoding="utf-8", newline="") as fh:
            aliases = [
                (row["district"].strip(), row["alias"].strip(), row["locality"].strip())
                for row in csv.DictReader(fh)
            ]
        return cls(localities, aliases)

    # ------------------------------------------------------------- queries

    @property
    def districts(self) -> list[str]:
        return sorted(self._districts.values())

    def locality(self, district: str, name: str) -> Locality | None:
        return self._localities.get((_district_key(district), basic_clean(name)))

    def localities_for_pincode(self, district: str, pincode: str) -> list[str]:
        return sorted(self._by_pincode.get((_district_key(district), pincode.strip()), []))

    def _scan(self, dk: str, tokens: list[str]) -> list[tuple[int, int, str]]:
        """Longest-first, left-to-right alias matches as ``(start, end, canonical)``."""
        table = self._aliases.get(dk, {})
        found: list[tuple[int, int, str]] = []
        i = 0
        while i < len(tokens):
            for n in range(min(self._max_len, len(tokens) - i), 0, -1):
                canonical = table.get(tuple(tokens[i : i + n]))
                if canonical is not None:
                    found.append((i, i + n, canonical))
                    i += n
                    break
            else:
                i += 1
        return found

    def canonicalise(self, district: str, tokens: list[str]) -> list[str]:
        """Step 3: replace alias token sequences (English or Tamil) with the canonical
        locality's cleaned tokens. Tokens must be cleaned and abbreviation-expanded."""
        dk = _district_key(district)
        out: list[str] = []
        last = 0
        for start, end, canonical in self._scan(dk, tokens):
            out.extend(tokens[last:start])
            out.extend(basic_clean(canonical).split())
            last = end
        out.extend(tokens[last:])
        return out

    def resolve(self, district: str, text: str) -> Resolution | None:
        """Map free locality text to a canonical locality in ``district``, or ``None``."""
        dk = _district_key(district)
        if dk not in self._districts or not text:
            return None
        name = self._districts[dk]
        tokens = _drop_district_phrase(dk, expand_abbreviations(basic_clean(text).split()))
        if not tokens:
            return None
        found = self._resolve_tokens(dk, name, tokens)
        if found is None and "tn" in tokens:
            # "TN" usually means Tamil Nadu, but listings also abbreviate "Town" to "Tn".
            # Try "town" only when the text did not resolve as written.
            found = self._resolve_tokens(dk, name, ["town" if t == "tn" else t for t in tokens])
        return found

    def _resolve_tokens(self, dk: str, name: str, tokens: list[str]) -> Resolution | None:
        canonical = self._aliases[dk].get(tuple(tokens))
        if canonical is not None:
            return Resolution(name, canonical, "exact")

        hits = {c for _, _, c in self._scan(dk, tokens)}
        if len(hits) == 1:
            return Resolution(name, hits.pop(), "contains")
        if len(hits) > 1:
            return None

        sounds = self._sounds[dk].get(_sound(tokens), set())
        if len(sounds) == 1:
            return Resolution(name, next(iter(sounds)), "phonetic")
        return None
