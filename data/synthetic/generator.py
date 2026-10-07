r"""Synthetic data generator for Verified Stays (module M1).

Writes a fictional licence registry, platform-style listings and ground truth for a
dev set (threshold tuning) and a test set (run once after tuning), plus a name
spot-check list. EVERYTHING IS FICTIONAL. Locality names, pincodes and centroids are
real places (approximate [A]); property names, licence numbers and addresses are invented.
There are no owner names, phone numbers or emails anywhere.

Usage (from the repo root):
    python tasks.py seed
    python data/synthetic/generator.py [--dev-seed 101] [--test-seed 202] [--out DIR]

Determinism: the same seeds give byte-identical files. Only `random.Random(seed)` is used,
nothing iterates over an unordered set, dates come from REFERENCE_DATE (never today()),
and files are UTF-8 without BOM with "\n" line endings.

Dev vs test (D12, D22): the test set uses a different seed, different noise templates
and fresh property names (no name core used in dev appears in test).
LIMITATION: dev and test share the same 8 districts, localities and gazetteer, so the
test set is not fully independent of the dev set. Results on this data show that the
method works on synthetic data; they do not predict real-world accuracy.

Licence number format (invented, not modelled on any government scheme):
    SYN-<district code>-<5 digits>-<check letter>      e.g. SYN-NLG-04817-K
The check letter is CHECK_ALPHABET[sum((i+1) * ord(ch)) % 24] over "<code><digits>".

Tamil text (gazetteer aliases, address_ta, Tamil-script noise) is machine-generated and
needs review by a native speaker (D24, Q3).
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from indic_transliteration import sanscript

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "out"
DEV_SEED = 101
TEST_SEED = 202
REFERENCE_DATE = date(2026, 4, 1)

DISTRICT_CODES: dict[str, str] = {
    "Nilgiris": "NLG",
    "Coimbatore": "CBE",
    "Madurai": "MDU",
    "Dindigul": "DGL",
    "Kanyakumari": "KNK",
    "Thanjavur": "TNJ",
    "Ramanathapuram": "RMD",
    "Chennai": "CHN",
}
DISTRICTS = list(DISTRICT_CODES)

# Registry entries per district and listing totals per set. Nilgiris is the dense demo
# district: 36 + 24 = 60 registry entries across dev + test.
SET_CONFIG: dict[str, dict] = {
    "dev": {"prefix": "DEV", "nilgiris": 36, "other": 18, "listings": 300},
    "test": {"prefix": "TST", "nilgiris": 24, "other": 12, "listings": 200},
}

LISTING_TYPES = ["clean", "noisy", "wrong_or_expired", "no_counterpart", "hard_negative"]
TYPE_SHARES = {
    "clean": 0.20,
    "noisy": 0.35,
    "wrong_or_expired": 0.12,
    "no_counterpart": 0.18,
    "hard_negative": 0.15,
}
DEV_NOISE = ["abbreviation", "reorder", "typo"]  # applied in this order
TEST_NOISE = ["alt_spelling", "merged", "dropped_locality", "tamil"]  # applied in this order
NOISE_BY_SET = {"dev": DEV_NOISE, "test": TEST_NOISE}
DEMO_QUOTAS = {
    "clean": 5,
    "noisy": 8,
    "wrong_or_expired": 4,
    "no_counterpart": 4,
    "hard_negative": 4,
}

REGISTRY_COLUMNS = [
    "licence_no",
    "name",
    "address_en",
    "address_ta",
    "locality",
    "pincode",
    "lat",
    "lng",
    "category",
    "valid_from",
    "valid_to",
    "status",
    "district",
]
# `listing_id` is a synthetic-only leading column so ground truth can be joined (D35).
LISTING_COLUMNS = [
    "listing_id",
    "platform",
    "ref_url",
    "title",
    "locality_text",
    "pincode",
    "lat",
    "lng",
    "claimed_licence_no",
    "notes",
    "district",
]
GROUND_TRUTH_COLUMNS = ["listing_id", "true_registry_id", "type", "noise"]

SYNTHETIC_NOTICE = (
    "Demonstration data - fictional.\n"
    "Every property name, licence number and address in these files is invented. Locality\n"
    "names and pincodes are real places only. No owners, phone numbers or emails exist.\n"
    "Tamil text is machine-generated and needs native-speaker review.\n"
    "Results on this data do not predict real-world accuracy.\n"
)

CHECK_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"

FIRST_WORDS = (
    "Amber Banyan Bamboo Birch Bluebell Cardamom Cedar Clover Coral Cypress Driftwood "
    "Eucalyptus Fern Firefly Hazel Hornbill Indigo Ivory Jacaranda Jasmine Juniper "
    "Kingfisher Lantern Laurel Lotus Magnolia Mango Maple Marigold Moonbeam Myna Neem "
    "Nutmeg Orchid Peacock Pepper Plum Quill Rosewood Saffron Sandal Sapphire Silver "
    "Skylark Sparrow Tamarind Teak Thistle Velvet Wildflower Willow Wren"
).split()
SECOND_WORDS = (
    "Nest Haven Hollow Crest Grove Ridge Bough Glade Knoll Perch Nook Arbour Terrace "
    "Corner Court Retreat Acre Bower Den Burrow Loft Porch Garden Meadow"
).split()
GENERIC_BY_CATEGORY: dict[str, list[str]] = {
    "homestay": ["Homestay"],
    "lodge": ["Lodge", "Inn"],
    "guest_house": ["Guest House", "Residency"],
    "cottage": ["Cottage", "Cottages", "Stay"],
}
CATEGORIES = list(GENERIC_BY_CATEGORY)
GENERIC_TOKENS = {"homestay", "lodge", "inn", "guest", "house", "residency"}
GENERIC_TOKENS |= {"cottage", "cottages", "stay", "villa", "resort"}

STREETS: dict[str, str] = {
    "Church Road": "சர்ச் ரோடு",
    "Bazaar Street": "பஜார் தெரு",
    "Lake Road": "லேக் ரோடு",
    "Main Road": "மெயின் ரோடு",
    "Hospital Road": "ஆஸ்பத்திரி ரோடு",
    "School Street": "பள்ளி தெரு",
    "Temple Street": "கோவில் தெரு",
    "Station Road": "ஸ்டேஷன் ரோடு",
    "Market Road": "மார்க்கெட் ரோடு",
    "Hill Road": "ஹில் ரோடு",
    "Park Road": "பார்க் ரோடு",
    "East Street": "கிழக்கு தெரு",
    "West Street": "மேற்கு தெரு",
    "North Street": "வடக்கு தெரு",
    "South Street": "தெற்கு தெரு",
}

PLATFORMS = [
    ("platform_a", "https://platform-a.example/listing/", 45),
    ("platform_b", "https://platform-b.example/rooms/", 35),
    ("direct", "https://direct.example/stay/", 20),
]

# Dev noise: abbreviation swaps (title tokens and locality words).
ABBREVIATIONS: dict[str, str] = {
    "Homestay": "H/Stay",
    "Cottage": "Ctg",
    "Cottages": "Ctgs",
    "Residency": "Resi",
    "Lodge": "Ldg",
    "Garden": "Gdn",
    "Terrace": "Ter",
    "Court": "Ct",
    "Corner": "Cnr",
    "Meadow": "Mdw",
    "Retreat": "Rtrt",
    "Nagar": "Ngr",
    "Town": "Tn",
    "Puram": "Pm",
}
KEYBOARD_NEIGHBOURS = {
    "a": "s",
    "e": "r",
    "i": "o",
    "o": "p",
    "u": "y",
    "n": "m",
    "r": "t",
    "s": "d",
    "t": "y",
    "l": "k",
}

# Test noise: spelling variants that are NOT gazetteer aliases.
LOCALITY_ALT_SPELLINGS: dict[str, str] = {
    "Kotagiri": "Kothagiri",
    "Coonoor": "Kunnur",
    "Gudalur": "Kudalur",
    "Masinagudi": "Masinagudy",
    "Aruvankadu": "Aruvangadu",
    "Lovedale": "Love Dale",
    "Valparai": "Valparay",
    "Gandhipuram": "Ganthipuram",
    "Simmakkal": "Simmakal",
    "Tallakulam": "Thallakulam",
    "Kodaikanal": "Kodaikkanal",
    "Palani": "Pazhani",
    "Nagercoil": "Nagarkoil",
    "Kanyakumari": "Kanniyakumari",
    "Colachel": "Kolachel",
    "Kumbakonam": "Kumbhakonam",
    "Pattukkottai": "Pattukottai",
    "Rameswaram": "Rameshwaram",
    "Mandapam": "Mandabam",
    "Mylapore": "Mylapur",
}
NAME_SPELLING_RULES = [
    ("ee", "i"),
    ("oo", "u"),
    ("ph", "f"),
    ("ck", "k"),
    ("w", "v"),
    ("y", "i"),
    ("ou", "u"),
    ("ll", "l"),
    ("nn", "n"),
    ("c", "k"),
]
# Test noise: Tamil script. Generic words by hand; other words via a crude English->ITRANS
# phonetic pass and indic-transliteration. Machine-generated; needs review.
TAMIL_GENERICS = {
    "homestay": "ஹோம்ஸ்டே",
    "lodge": "லாட்ஜ்",
    "inn": "இன்",
    "guest": "கெஸ்ட்",
    "house": "ஹவுஸ்",
    "residency": "ரெசிடென்சி",
    "cottage": "காட்டேஜ்",
    "cottages": "காட்டேஜஸ்",
    "stay": "ஸ்டே",
}
ITRANS_RULES = [
    ("ck", "k"),
    ("ph", "f"),
    ("ee", "I"),
    ("ea", "I"),
    ("oo", "U"),
    ("ou", "au"),
    ("ow$", "o"),
    ("c(?=[eiy])", "s"),
    ("c", "k"),
    ("x", "ks"),
    ("q", "k"),
    ("w", "v"),
    ("y$", "i"),
    ("(?<=..)e$", ""),
    ("th", "\x01"),
    ("dh", "\x02"),
    ("t", "T"),
    ("d", "D"),
    ("\x01", "t"),
    ("\x02", "d"),
    ("z", "j"),
]


@dataclass(frozen=True)
class Locality:
    district: str
    name: str
    pincode: str
    lat: float
    lng: float
    tamil: str  # first Tamil alias from the gazetteer, "" if none


@dataclass
class RegistryEntry:
    licence_no: str
    core: tuple[str, str]
    name: str
    street: str
    door: int
    locality: Locality
    lat: float
    lng: float
    category: str
    valid_from: date
    valid_to: date
    status: str

    def row(self) -> list[str]:
        loc = self.locality
        return [
            self.licence_no,
            self.name,
            f"{self.door}, {self.street}, {loc.name}",
            f"{self.door}, {STREETS[self.street]}, {loc.tamil}" if loc.tamil else "",
            loc.name,
            loc.pincode,
            _coord(self.lat),
            _coord(self.lng),
            self.category,
            self.valid_from.isoformat(),
            self.valid_to.isoformat(),
            self.status,
            loc.district,
        ]


@dataclass
class Listing:
    listing_id: str
    platform: str
    ref_url: str
    title: str
    locality_text: str
    pincode: str
    lat: str
    lng: str
    claimed_licence_no: str
    district: str
    true_registry_id: str
    type: str
    noise: list[str] = field(default_factory=list)

    def row(self) -> list[str]:
        return [
            self.listing_id,
            self.platform,
            self.ref_url,
            self.title,
            self.locality_text,
            self.pincode,
            self.lat,
            self.lng,
            self.claimed_licence_no,
            "",
            self.district,
        ]

    def truth_row(self) -> list[str]:
        return [self.listing_id, self.true_registry_id, self.type, ";".join(self.noise)]


# ---------------------------------------------------------------- reference data


def load_localities() -> list[Locality]:
    tamil: dict[tuple[str, str], str] = {}
    for row in load_gazetteer():
        key = (row["district"], row["locality"])
        if row["script"] == "tamil" and key not in tamil:
            tamil[key] = row["alias"]
    with open(HERE / "localities.csv", encoding="utf-8", newline="") as fh:
        return [
            Locality(
                r["district"],
                r["locality"],
                r["pincode"],
                float(r["lat"]),
                float(r["lng"]),
                tamil.get((r["district"], r["locality"]), ""),
            )
            for r in csv.DictReader(fh)
        ]


def load_gazetteer() -> list[dict[str, str]]:
    with open(HERE / "gazetteer.csv", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def load_blocklist() -> list[tuple[str, ...]]:
    entries = []
    for line in (HERE / "realname_blocklist.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip().lower()
        if line and not line.startswith("#"):
            entries.append(tuple(line.split()))
    return entries


def name_core_tokens(name: str) -> list[str]:
    """Lowercase name tokens with generic words (homestay, lodge, ...) removed."""
    tokens = re.findall(r"[a-z']+", name.lower())
    return [t for t in tokens if t not in GENERIC_TOKENS]


def is_blocked(name: str, blocklist: list[tuple[str, ...]]) -> bool:
    core = name_core_tokens(name)
    joined = "".join(core)
    for entry in blocklist:
        n = len(entry)
        if any(tuple(core[i : i + n]) == entry for i in range(len(core) - n + 1)):
            return True
        if joined == "".join(entry):
            return True
    return False


# ---------------------------------------------------------------- helpers


def _coord(value: float) -> str:
    return f"{value:.5f}"


def jitter(rng: random.Random, lat: float, lng: float, max_km: float) -> tuple[float, float]:
    dist = max_km * math.sqrt(rng.random())
    angle = rng.uniform(0, 2 * math.pi)
    dlat = dist * math.cos(angle) / 111.0
    dlng = dist * math.sin(angle) / (111.0 * math.cos(math.radians(lat)))
    return round(lat + dlat, 5), round(lng + dlng, 5)


def check_letter(code: str, digits: str) -> str:
    total = sum((i + 1) * ord(ch) for i, ch in enumerate(code + digits))
    return CHECK_ALPHABET[total % len(CHECK_ALPHABET)]


def make_licence(code: str, number: int, valid: bool = True) -> str:
    digits = f"{number:05d}"
    letter = check_letter(code, digits)
    if not valid:
        letter = CHECK_ALPHABET[(CHECK_ALPHABET.index(letter) + 7) % len(CHECK_ALPHABET)]
    return f"SYN-{code}-{digits}-{letter}"


def allocate(total: int, weights: dict[str, float]) -> dict[str, int]:
    """Largest-remainder allocation; ties broken by key order."""
    wsum = sum(weights.values())
    raw = {k: total * w / wsum for k, w in weights.items()}
    counts = {k: int(v) for k, v in raw.items()}
    rest = total - sum(counts.values())
    order = sorted(weights, key=lambda k: (-(raw[k] - counts[k]), list(weights).index(k)))
    for k in order[:rest]:
        counts[k] += 1
    return counts


def weighted_choice(rng: random.Random, items: list, weights: list[int]):
    return rng.choices(items, weights=weights, k=1)[0]


class NameFactory:
    """Unique (first, second) name cores per run; test never reuses a dev core."""

    def __init__(self, rng: random.Random, used: set[tuple[str, str]], blocklist) -> None:
        self.rng = rng
        self.used = used
        self.blocklist = blocklist

    def _accept(self, core: tuple[str, str], name: str) -> bool:
        return core not in self.used and not is_blocked(name, self.blocklist)

    def new(self, category: str) -> tuple[tuple[str, str], str]:
        for _ in range(10_000):
            core = (self.rng.choice(FIRST_WORDS), self.rng.choice(SECOND_WORDS))
            name = f"{core[0]} {core[1]} {self.rng.choice(GENERIC_BY_CATEGORY[category])}"
            if self._accept(core, name):
                self.used.add(core)
                return core, name
        raise RuntimeError("name space exhausted")

    def sibling(self, core: tuple[str, str], category: str) -> tuple[tuple[str, str], str]:
        """A different name sharing one token with `core` (for hard negatives)."""
        for _ in range(10_000):
            if self.rng.random() < 0.5:
                new = (core[0], self.rng.choice(SECOND_WORDS))
            else:
                new = (self.rng.choice(FIRST_WORDS), core[1])
            name = f"{new[0]} {new[1]} {self.rng.choice(GENERIC_BY_CATEGORY[category])}"
            if new != core and self._accept(new, name):
                self.used.add(new)
                return new, name
        raise RuntimeError("no sibling name available")


# ---------------------------------------------------------------- noise


def _typo(rng: random.Random, title: str, locality_text: str) -> tuple[str, str] | None:
    tokens = title.split(" ")
    idx = [i for i, t in enumerate(tokens) if len(t) >= 4 and t.isalpha()]
    for _ in range(50):
        i = rng.choice(idx)
        word = tokens[i]
        p = rng.randrange(1, len(word) - 1)
        op = rng.choice(["swap", "drop", "double", "neighbour"])
        if op == "swap":
            new = word[:p] + word[p + 1] + word[p] + word[p + 2 :]
        elif op == "drop":
            new = word[:p] + word[p + 1 :]
        elif op == "double":
            new = word[:p] + word[p] + word[p:]
        else:
            ch = word[p].lower()
            if ch not in KEYBOARD_NEIGHBOURS:
                continue
            new = word[:p] + KEYBOARD_NEIGHBOURS[ch] + word[p + 1 :]
        if new != word:
            tokens[i] = new
            return " ".join(tokens), locality_text
    return None


def _abbreviation(rng: random.Random, title: str, locality_text: str) -> tuple[str, str] | None:
    title_tokens = title.split(" ")
    loc_tokens = locality_text.split(" ")
    options = [("t", i) for i, t in enumerate(title_tokens) if t in ABBREVIATIONS]
    options += [("l", i) for i, t in enumerate(loc_tokens) if t in ABBREVIATIONS]
    if "Guest House" in title:
        options.append(("gh", 0))
    if not options:
        return None
    where, i = rng.choice(options)
    if where == "gh":
        return title.replace("Guest House", "GH"), locality_text
    if where == "t":
        title_tokens[i] = ABBREVIATIONS[title_tokens[i]]
    else:
        loc_tokens[i] = ABBREVIATIONS[loc_tokens[i]]
    return " ".join(title_tokens), " ".join(loc_tokens)


def _reorder(rng: random.Random, title: str, locality_text: str) -> tuple[str, str] | None:
    tokens = title.split(" ")
    core = [t for t in tokens if t.lower() not in GENERIC_TOKENS]
    generic = [t for t in tokens if t.lower() in GENERIC_TOKENS]
    if rng.random() < 0.5 and generic:
        new = generic + core
    else:
        new = core[::-1] + generic
    result = " ".join(new)
    return (result, locality_text) if result != title else None


def _alt_spelling(rng: random.Random, title: str, locality_text: str) -> tuple[str, str] | None:
    tokens = title.split(" ")
    changes = []
    for i, tok in enumerate(tokens):
        if tok.lower() in GENERIC_TOKENS:
            continue
        for old, new in NAME_SPELLING_RULES:
            if old in tok.lower():
                changes.append((i, old, new))
    loc_alt = LOCALITY_ALT_SPELLINGS.get(locality_text)
    if not changes and not loc_alt:
        return None
    if changes:
        i, old, new = rng.choice(changes)
        word = tokens[i].lower().replace(old, new, 1)
        tokens[i] = word[:1].upper() + word[1:]
    if loc_alt and (not changes or rng.random() < 0.5):
        locality_text = loc_alt
    return " ".join(tokens), locality_text


def _merged(rng: random.Random, title: str, locality_text: str) -> tuple[str, str] | None:
    tokens = title.split(" ")
    if len(tokens) < 2:
        return None
    i = rng.randrange(len(tokens) - 1)
    merged = tokens[i] + tokens[i + 1].lower()
    return " ".join(tokens[:i] + [merged] + tokens[i + 2 :]), locality_text


def _to_tamil(word: str) -> str:
    w = word.lower()
    if w in TAMIL_GENERICS:
        return TAMIL_GENERICS[w]
    for old, new in ITRANS_RULES:
        w = re.sub(old, new, w)
    return sanscript.transliterate(w, sanscript.ITRANS, sanscript.TAMIL)


def _make_tamil(alias_to_locality: dict[tuple[str, str], Locality], district: str):
    def apply(rng: random.Random, title: str, locality_text: str) -> tuple[str, str] | None:
        tamil_title = " ".join(_to_tamil(t) for t in re.findall(r"[A-Za-z']+", title))
        loc = alias_to_locality.get((district, locality_text))
        if loc is not None and loc.tamil:
            locality_text = loc.tamil
        return tamil_title, locality_text

    return apply


def _make_dropped(district: str):
    def apply(rng: random.Random, title: str, locality_text: str) -> tuple[str, str] | None:
        return title, f"{district} district"

    return apply


# ---------------------------------------------------------------- generation


def _cycler(rng: random.Random, items: list[RegistryEntry]):
    """Return a callable yielding every item once (shuffled) before any repeats."""
    pool: list[RegistryEntry] = []

    def pick() -> RegistryEntry:
        if not pool:
            pool.extend(rng.sample(items, len(items)))
        return pool.pop()

    return pick


@dataclass
class DataSet:
    name: str
    registry: list[RegistryEntry]
    listings: list[Listing]
    demo_ids: list[str]


def _english_aliases(gazetteer: list[dict[str, str]]) -> dict[tuple[str, str], list[str]]:
    out: dict[tuple[str, str], list[str]] = {}
    for row in gazetteer:
        if row["script"] == "latin":
            out.setdefault((row["district"], row["locality"]), []).append(row["alias"])
    return out


def generate_set(
    set_name: str,
    seed: int,
    localities: list[Locality],
    gazetteer: list[dict[str, str]],
    used_cores: set[tuple[str, str]],
    blocklist: list[tuple[str, ...]],
) -> DataSet:
    cfg = SET_CONFIG[set_name]
    rng = random.Random(seed)
    names = NameFactory(rng, used_cores, blocklist)
    by_key = {(loc.district, loc.name): loc for loc in localities}
    aliases = _english_aliases(gazetteer)
    alias_to_locality = {
        (district, alias): by_key[(district, name)]
        for (district, name), names_ in aliases.items()
        for alias in names_
    }
    licence_numbers: set[int] = set()

    def new_number() -> int:
        while True:
            n = rng.randint(1, 99_999)
            if n not in licence_numbers:
                licence_numbers.add(n)
                return n

    # Registry -----------------------------------------------------------
    registry: list[RegistryEntry] = []
    for district in DISTRICTS:
        locs = [loc for loc in localities if loc.district == district]
        weights = [3 if loc.name == "Ooty" else 2 if loc.name == "Coonoor" else 1 for loc in locs]
        n = cfg["nilgiris"] if district == "Nilgiris" else cfg["other"]
        n_expired = max(2, round(0.14 * n))
        n_suspended = max(1, round(0.06 * n))
        statuses = ["expired"] * n_expired + ["suspended"] * n_suspended
        statuses += ["active"] * (n - len(statuses))
        rng.shuffle(statuses)
        for status in statuses:
            loc = weighted_choice(rng, locs, weights)
            category = rng.choice(CATEGORIES)
            core, name = names.new(category)
            lat, lng = jitter(rng, loc.lat, loc.lng, 1.5)
            if status == "expired":
                valid_to = REFERENCE_DATE - timedelta(days=rng.randint(10, 400))
                valid_from = valid_to - timedelta(days=rng.randint(365, 1500))
            else:
                valid_from = REFERENCE_DATE - timedelta(days=rng.randint(100, 1500))
                valid_to = REFERENCE_DATE + timedelta(days=rng.randint(30, 1000))
            registry.append(
                RegistryEntry(
                    licence_no=make_licence(DISTRICT_CODES[district], new_number()),
                    core=core,
                    name=name,
                    street=rng.choice(sorted(STREETS)),
                    door=rng.randint(1, 250),
                    locality=loc,
                    lat=lat,
                    lng=lng,
                    category=category,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    status=status,
                )
            )

    # Listings -----------------------------------------------------------
    reg_counts = {d: sum(1 for r in registry if r.locality.district == d) for d in DISTRICTS}
    listing_counts = allocate(cfg["listings"], {d: float(c) for d, c in reg_counts.items()})
    noise_order = NOISE_BY_SET[set_name]
    listings: list[Listing] = []
    counter = 0

    for district in DISTRICTS:
        entries = [r for r in registry if r.locality.district == district]
        active = [r for r in entries if r.status == "active"]
        lapsed = [r for r in entries if r.status != "active"]
        locs = [loc for loc in localities if loc.district == district]
        type_counts = allocate(listing_counts[district], TYPE_SHARES)
        types = [t for t in LISTING_TYPES for _ in range(type_counts[t])]
        rng.shuffle(types)
        next_active = _cycler(rng, active)
        templates = {
            "typo": _typo,
            "abbreviation": _abbreviation,
            "reorder": _reorder,
            "alt_spelling": _alt_spelling,
            "merged": _merged,
            "dropped_locality": _make_dropped(district),
            "tamil": _make_tamil(alias_to_locality, district),
        }

        def locality_text_for(loc: Locality, canonical: bool) -> str:
            if canonical:
                return loc.name
            return rng.choice(aliases[(loc.district, loc.name)])

        for ltype in types:
            counter += 1
            listing_id = f"{cfg['prefix']}-L{counter:04d}"
            platform, base_url, _ = weighted_choice(rng, PLATFORMS, [p[2] for p in PLATFORMS])
            claimed = ""
            truth = ""
            noise: list[str] = []
            if ltype in ("clean", "noisy", "wrong_or_expired"):
                if ltype == "wrong_or_expired":
                    sub = weighted_choice(
                        rng, ["expired", "unknown", "malformed", "other"], [40, 25, 15, 20]
                    )
                    entry = rng.choice(lapsed) if sub == "expired" else next_active()
                    code = DISTRICT_CODES[district]
                    if sub == "expired":
                        claimed = entry.licence_no
                    elif sub == "unknown":
                        claimed = make_licence(code, new_number())
                    elif sub == "malformed":
                        claimed = make_licence(code, new_number(), valid=False)
                    else:
                        others = [r for r in entries if r is not entry]
                        claimed = rng.choice(others).licence_no
                else:
                    entry = next_active()
                    if rng.random() < 0.5:
                        claimed = entry.licence_no
                truth = entry.licence_no
                loc = entry.locality
                title = entry.name
                loc_text = locality_text_for(loc, canonical=(ltype == "clean"))
                lat, lng = jitter(rng, entry.lat, entry.lng, 0.3)
                if ltype == "noisy":
                    applicable = [
                        t for t in noise_order if templates[t](random.Random(0), title, loc_text)
                    ]
                    k = 1 if rng.random() < 0.6 or len(applicable) < 2 else 2
                    chosen = set(rng.sample(applicable, k))
                    for t in noise_order:
                        if t in chosen:
                            result = templates[t](rng, title, loc_text)
                            if result is not None:
                                title, loc_text = result
                                noise.append(t)
            elif ltype == "hard_negative":
                entry = rng.choice(entries)
                loc = entry.locality
                _, title = names.sibling(entry.core, rng.choice(CATEGORIES))
                loc_text = locality_text_for(loc, canonical=rng.random() < 0.5)
                lat, lng = jitter(rng, entry.lat, entry.lng, 0.3)
            else:  # no_counterpart
                loc = rng.choice(locs)
                _, title = names.new(rng.choice(CATEGORIES))
                loc_text = locality_text_for(loc, canonical=rng.random() < 0.5)
                lat, lng = jitter(rng, loc.lat, loc.lng, 1.5)

            pincode = loc.pincode if rng.random() < 0.8 else ""
            if "dropped_locality" in noise:
                pincode = ""
            has_coords = rng.random() < 0.7
            listings.append(
                Listing(
                    listing_id=listing_id,
                    platform=platform,
                    ref_url=base_url + listing_id.lower(),
                    title=title,
                    locality_text=loc_text,
                    pincode=pincode,
                    lat=_coord(lat) if has_coords else "",
                    lng=_coord(lng) if has_coords else "",
                    claimed_licence_no=claimed,
                    district=district,
                    true_registry_id=truth,
                    type=ltype,
                    noise=noise,
                )
            )

    demo_ids: list[str] = []
    if set_name == "dev":
        nilgiris = [lst for lst in listings if lst.district == "Nilgiris"]
        for ltype, quota in DEMO_QUOTAS.items():
            pool = [lst.listing_id for lst in nilgiris if lst.type == ltype]
            demo_ids += rng.sample(pool, min(quota, len(pool)))
        demo_ids.sort()

    return DataSet(set_name, registry, listings, demo_ids)


# ---------------------------------------------------------------- output


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def write_set(ds: DataSet, out: Path) -> None:
    folder = out / ds.name
    _write_csv(folder / "registry.csv", REGISTRY_COLUMNS, [r.row() for r in ds.registry])
    _write_csv(folder / "listings.csv", LISTING_COLUMNS, [lst.row() for lst in ds.listings])
    _write_csv(
        folder / "ground_truth.csv",
        GROUND_TRUTH_COLUMNS,
        [lst.truth_row() for lst in ds.listings],
    )
    if ds.demo_ids:
        demo = set(ds.demo_ids)
        rows = [lst.row() for lst in ds.listings if lst.listing_id in demo]
        _write_csv(folder / "demo_listings.csv", LISTING_COLUMNS, rows)


def write_spotcheck(sets: list[DataSet], out: Path) -> None:
    rows: set[tuple[str, str, str, str]] = set()
    for ds in sets:
        for r in ds.registry:
            rows.add((ds.name, r.locality.district, "registry", r.name))
        for lst in ds.listings:
            if lst.type in ("no_counterpart", "hard_negative"):
                rows.add((ds.name, lst.district, "listing_only", lst.title))
    _write_csv(out / "name_spotcheck.csv", ["set", "district", "kind", "name"], sorted(rows))


def generate(out: Path = DEFAULT_OUT, dev_seed: int = DEV_SEED, test_seed: int = TEST_SEED):
    if dev_seed == test_seed:
        raise ValueError("dev and test seeds must differ (D12)")
    localities = load_localities()
    gazetteer = load_gazetteer()
    blocklist = load_blocklist()
    used_cores: set[tuple[str, str]] = set()
    dev = generate_set("dev", dev_seed, localities, gazetteer, used_cores, blocklist)
    test = generate_set("test", test_seed, localities, gazetteer, used_cores, blocklist)
    for ds in (dev, test):
        write_set(ds, out)
    write_spotcheck([dev, test], out)
    (out / "README_SYNTHETIC.txt").write_text(SYNTHETIC_NOTICE, encoding="utf-8", newline="\n")
    return dev, test


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dev-seed", type=int, default=DEV_SEED)
    parser.add_argument("--test-seed", type=int, default=TEST_SEED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    dev, test = generate(args.out, args.dev_seed, args.test_seed)
    for ds in (dev, test):
        print(f"{ds.name}: {len(ds.registry)} registry, {len(ds.listings)} listings")
    print(f"Written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
