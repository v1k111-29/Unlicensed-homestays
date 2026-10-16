"""Text normalisation for matching (data-and-matching.md §4). Pure Python, no Django.

What this file is for: it turns a messy name or address (typed by a homestay owner or a
tourist, in English or Tamil) into a clean list of words that can be compared fairly.

Who calls it: ``features.py`` (for names and places) and ``gazetteer.py`` (for locality
aliases). Tests check each step on its own.

Key idea in plain words: the steps run in a fixed order. Each step removes one kind of noise
(punctuation, short forms, Tamil script, pincodes, generic words like "homestay").

Steps, each a separate function so it can be tested on its own:

1. ``basic_clean``          Unicode NFC, casefold, punctuation -> space, initials joined.
2. ``expand_abbreviations`` rd -> road, ngr -> nagar, ctg -> cottage, ...
3. gazetteer aliases        ``Gazetteer.canonicalise`` (see ``gazetteer.py``), keyed by
                            ``(district, alias)``; never across districts.
4. ``tamil_to_latin``       remaining Tamil-script tokens -> Latin (small lexicon first,
                            then ``indic-transliteration``) [A: imperfect for names].
5. ``extract_pincode``      first 6-digit Indian pincode; removed from the tokens.
6. ``remove_stopwords`` / ``remove_generic_words`` (homestay, villa, cottage, ...).

``phonetic_key`` is an extra comparison key that collapses spelling differences common in
Tamil romanisation (k/g, t/d/th, s/ch/j, p/b/f, zh/l, doubled letters).

Everything here is deterministic: same input, same output; no randomness, no I/O.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING

from indic_transliteration import sanscript
from rapidfuzz.distance import OSA

# Imported only for type hints, so this module does not depend on the gazetteer at runtime.
if TYPE_CHECKING:
    from matching.gazetteer import Gazetteer

# ------------------------------------------------------------------ step 1: clean

# Apostrophes are removed without a space ("Mary's" -> "marys").
# The characters are: straight quote, curly quote, backtick, acute accent.
_JOIN_CHARS = re.compile(r"['’`´]")


def _is_kept(ch: str) -> bool:
    """True for characters that carry meaning: letters, digits and combining marks."""
    # Letters, combining marks (Tamil vowel signs and virama are Mn/Mc) and digits.
    # The Unicode category starts with L (letter), M (mark) or N (number).
    return unicodedata.category(ch)[0] in "LMN"


def _is_initial(token: str) -> bool:
    """True for a single lowercase Latin letter, such as the "r" in "r s puram"."""
    return len(token) == 1 and "a" <= token <= "z"


def _join_initials(tokens: list[str]) -> list[str]:
    """Join runs of 2+ single Latin letters: ``r s puram`` -> ``rs puram``."""
    out: list[str] = []
    # ``run`` collects single letters until a longer token ends the run.
    run: list[str] = []
    # The extra "" at the end flushes the last run, because the loop only writes a run
    # when it sees a token that is not a single letter.
    for tok in [*tokens, ""]:
        if _is_initial(tok):
            run.append(tok)
            continue
        # A run of 2 or more single letters is an initials pattern, so join it into one word.
        if len(run) >= 2:
            out.append("".join(run))
        else:
            out.extend(run)
        run = []
        if tok:
            out.append(tok)
    return out


def basic_clean(text: str) -> str:
    """Step 1: NFC, casefold, strip punctuation, collapse whitespace, join initials."""
    # NFC merges accented characters into single code points, so they compare equal.
    # Casefold is a stronger form of lowercasing that also works for non-English letters.
    text = unicodedata.normalize("NFC", text or "").casefold()
    text = _JOIN_CHARS.sub("", text)
    text = "".join(ch if _is_kept(ch) else " " for ch in text)
    return " ".join(_join_initials(text.split()))


def tokenize(text: str) -> list[str]:
    """Clean the text and split it into a list of words."""
    return basic_clean(text).split()


# ------------------------------------------------------------ step 2: abbreviations

# Short forms that are expanded to a full word or words. Keys and values are already lowercase.
ABBREVIATIONS: dict[str, tuple[str, ...]] = {
    # addresses
    "rd": ("road",),
    "st": ("street",),
    "str": ("street",),
    "ngr": ("nagar",),
    "nagr": ("nagar",),
    "pm": ("puram",),
    "mn": ("main",),
    # property names
    "ctg": ("cottage",),
    "ctgs": ("cottages",),
    "gh": ("guest", "house"),
    "resi": ("residency",),
    "ldg": ("lodge",),
    "gdn": ("garden",),
    "ter": ("terrace",),
    "ct": ("court",),
    "cnr": ("corner",),
    "mdw": ("meadow",),
    "rtrt": ("retreat",),
}
# Multi-token forms, checked before single tokens ("h/stay" cleans to "h stay").
ABBREVIATION_PHRASES: dict[tuple[str, ...], tuple[str, ...]] = {
    ("h", "stay"): ("homestay",),
    ("home", "stay"): ("homestay",),
    ("guesthouse",): ("guest", "house"),
}
# The longest phrase length. The expander tries lengths from this down to 1.
_MAX_PHRASE = max(len(k) for k in ABBREVIATION_PHRASES)


def expand_abbreviations(tokens: list[str]) -> list[str]:
    """Step 2: expand known abbreviations (tokens must already be cleaned)."""
    out: list[str] = []
    i = 0
    while i < len(tokens):
        # Try the longest phrase first, so "h stay" wins over a single-word match.
        for n in range(_MAX_PHRASE, 0, -1):
            phrase = tuple(tokens[i : i + n])
            if len(phrase) == n and phrase in ABBREVIATION_PHRASES:
                out.extend(ABBREVIATION_PHRASES[phrase])
                i += n
                break
        else:
            # No phrase matched. The "else" of a for loop runs only when the loop did not break.
            out.extend(ABBREVIATIONS.get(tokens[i], (tokens[i],)))
            i += 1
    return out


# --------------------------------------------------------------- step 4: Tamil

# Matches any character in the Tamil Unicode block (U+0B80 to U+0BFF).
_TAMIL_RE = re.compile(r"[஀-௿]")

# Common loan/generic words, mapped by hand so they become the English word (and can then
# be removed as generic words). Machine-written; needs review by a native speaker (Q3).
TAMIL_LEXICON: dict[str, str] = {
    "ஹோம்ஸ்டே": "homestay",
    "லாட்ஜ்": "lodge",
    "விடுதி": "lodge",
    "இன்": "inn",
    "கெஸ்ட்": "guest",
    "ஹவுஸ்": "house",
    "ரெசிடென்சி": "residency",
    "காட்டேஜ்": "cottage",
    "காட்டேஜஸ்": "cottages",
    "ஸ்டே": "stay",
    "வில்லா": "villa",
    "ரிசார்ட்": "resort",
    "ஹோட்டல்": "hotel",
    "ரோடு": "road",
    "சாலை": "road",
    "தெரு": "street",
    "நகர்": "nagar",
    "புரம்": "puram",
    "மெயின்": "main",
}

# indic-transliteration 2.3.x renders Tamil stops with the voiced-aspirate letter of each
# group (க -> gh, த -> dh, ப -> bh, ச -> jh) [V: tested]. Map them to the usual romanisation.
# Each pair is (what the library writes, what we want).
_ISO_FIXES: list[tuple[str, str]] = [
    ("ḍh", "d"),
    ("ṭh", "t"),
    ("dh", "th"),
    ("gh", "k"),
    ("jh", "s"),
    ("bh", "p"),
    ("ḻ", "zh"),
    ("ś", "sh"),
    ("ṣ", "sh"),
    ("ṟ", "r"),
]


def _strip_marks(text: str) -> str:
    """Remove accents and other combining marks, so "ā" becomes "a"."""
    # NFKD splits each accented letter into a base letter plus separate mark characters.
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def has_tamil(text: str) -> bool:
    """True if the text contains at least one Tamil-script character."""
    return bool(_TAMIL_RE.search(text))


def tamil_token_to_latin(token: str) -> str:
    """Transliterate one Tamil-script token to plain lowercase ASCII-ish Latin."""
    if not has_tamil(token):
        return token
    token = unicodedata.normalize("NFC", token)
    # The hand-made lexicon wins, because the library spells loan words poorly.
    if token in TAMIL_LEXICON:
        return TAMIL_LEXICON[token]
    latin = sanscript.transliterate(token, sanscript.TAMIL, sanscript.ISO)
    for old, new in _ISO_FIXES:
        latin = latin.replace(old, new)
    latin = _strip_marks(latin).lower()
    # Keep only letters and digits, so no punctuation is left in the result.
    return "".join(ch for ch in latin if ch.isalnum())


def tamil_to_latin(tokens: list[str]) -> list[str]:
    """Step 4: transliterate every Tamil-script token; Latin tokens pass through."""
    out = [tamil_token_to_latin(t) for t in tokens]
    # Drop tokens that became empty, for example a token that was only punctuation.
    return [t for t in out if t]


# ------------------------------------------------------------- step 5: pincode

# Indian pincodes: 6 digits, first digit 1-9; "643 001" is accepted too.
# The lookarounds (?<!\d) and (?!\d) stop the match inside a longer number.
_PINCODE_RE = re.compile(r"(?<!\d)([1-9]\d{2})\s?(\d{3})(?!\d)")


def extract_pincode(text: str) -> tuple[str | None, str]:
    """Step 5: return ``(pincode or None, text with that pincode removed)``."""
    m = _PINCODE_RE.search(text or "")
    if not m:
        return None, text or ""
    # The two groups are the first three and last three digits. Join them with no space.
    # The pincode is replaced by a space, so the words on each side stay separate.
    return m.group(1) + m.group(2), text[: m.start()] + " " + text[m.end() :]


# ---------------------------------------------------- step 6: stopwords, generics

# Small filler words that carry no meaning for matching.
STOPWORDS: frozenset[str] = frozenset({"the", "and", "of", "at", "a", "an"})
# Accommodation words such as "homestay" or "villa". Every listing has them, so they say
# nothing about which place it is.
GENERIC_WORDS: frozenset[str] = frozenset(
    {
        "homestay",
        "homestays",
        "stay",
        "stays",
        "villa",
        "villas",
        "cottage",
        "cottages",
        "resort",
        "resorts",
        "inn",
        "lodge",
        "lodges",
        "guest",
        "house",
        "residency",
        "hotel",
    }
)
# Long generic words also match with one typo ("cotage", "hmestay"). Short ones do not:
# "house"/"horse" or "inn"/"ink" would remove real name words.
# The 7 is the minimum length for a typo match. Shorter words are too easy to hit by chance.
_FUZZY_GENERIC = tuple(sorted(w for w in GENERIC_WORDS if len(w) >= 7))


def remove_stopwords(tokens: list[str]) -> list[str]:
    """Drop the filler words in ``STOPWORDS``."""
    return [t for t in tokens if t not in STOPWORDS]


def is_generic(token: str) -> bool:
    """True if the token is a generic word, or a one-typo version of a long generic word."""
    if token in GENERIC_WORDS:
        return True
    # Tokens shorter than 6 letters are never fuzzy-matched (see the note above).
    if len(token) < 6:
        return False
    # OSA distance counts a typo as one edit. A cutoff of 1 stops the check early when the
    # distance is above 1, which keeps it fast.
    return any(OSA.distance(token, g, score_cutoff=1) <= 1 for g in _FUZZY_GENERIC)


def remove_generic_words(tokens: list[str]) -> list[str]:
    """Step 6: drop generic accommodation words. Keeps all tokens if nothing would remain."""
    kept = [t for t in tokens if not is_generic(t)]
    # If the name is only generic words (for example "Homestay"), keep them so it is not empty.
    return kept or list(tokens)


# ------------------------------------------------------------- phonetic key

# Sound-based rewrite rules, applied in order. Each is (regex, replacement).
# They turn spellings that sound alike into one shared form, so "Kothagiri" and "Kotagiri"
# both become "kotakiri". The order matters: a two-letter rule such as "ch" must run before
# the single-letter rule for "c", or "ch" would be split up first.
_KEY_RULES: list[tuple[str, str]] = [
    ("ow$", "o"),
    ("c(?=[eiy])", "s"),
    ("zh", "l"),
    ("th", "t"),
    ("dh", "t"),
    ("kh", "k"),
    ("gh", "k"),
    ("ch", "s"),
    ("sh", "s"),
    ("jh", "s"),
    ("bh", "p"),
    ("ph", "p"),
    ("ee", "i"),
    ("ea", "i"),
    ("oo", "u"),
    ("ou", "u"),
    ("au", "u"),
    ("(?<=..[^aeiou])e$", ""),  # silent final e: grove -> grov
    ("x", "ks"),
    ("q", "k"),
    ("c", "k"),
    ("g", "k"),
    ("d", "t"),
    ("j", "s"),
    ("z", "s"),
    ("b", "p"),
    ("f", "p"),
    ("w", "v"),
    ("y", "i"),
]
# Compile each rule once, so the work is not repeated for every token.
_KEY_PATTERNS = [(re.compile(p), r) for p, r in _KEY_RULES]
# An "h" that comes after another letter is silent in most Tamil romanised names.
_NON_INITIAL_H = re.compile(r"(?<=.)h")
# Two or more of the same letter in a row, collapsed to one ("ll" -> "l").
_REPEATS = re.compile(r"(.)\1+")


def phonetic_key(token: str) -> str:
    """Coarse sound key for one Latin token: ``Kothagiri`` and ``Kotagiri`` -> ``kotakiri``.

    Non-ASCII tokens (e.g. untransliterated scripts) are returned unchanged.
    """
    t = token.lower()
    if not t.isascii():
        return t
    for pattern, new in _KEY_PATTERNS:
        t = pattern.sub(new, t)
    t = _NON_INITIAL_H.sub("", t)
    return _REPEATS.sub(r"\1", t)


# ------------------------------------------------------------------ pipeline


@dataclass(frozen=True)
class NormalisedText:
    """Result of the full pipeline. ``tokens`` keep generic words; ``core_tokens`` do not."""

    original: str  # the text as it was typed, kept for display
    tokens: tuple[str, ...]  # all the words, with generic words kept
    core_tokens: tuple[str, ...]  # the words that identify the place (generic words removed)
    pincode: str | None  # a pincode found in the text, if any

    @property
    def text(self) -> str:
        """All the words joined with spaces."""
        return " ".join(self.tokens)

    @property
    def core(self) -> str:
        """The identifying words joined with spaces, used for fuzzy text comparison."""
        return " ".join(self.core_tokens)

    @property
    def keys(self) -> tuple[str, ...]:
        """Phonetic keys of the core tokens."""
        return tuple(phonetic_key(t) for t in self.core_tokens)

    @property
    def compact(self) -> str:
        """Core without spaces, for merged-word comparison ("cloverloft")."""
        return "".join(self.core_tokens)


def _normalise(
    text: str,
    *,
    drop_generic: bool,
    district: str | None,
    gazetteer: Gazetteer | None,
) -> NormalisedText:
    """Run steps 5, 1, 2, 3, 4 and 6 in that order. ``drop_generic`` controls step 6's
    removal of generic words. Addresses keep them, names drop them from ``core``."""
    # Step 5 runs first, so the digits of the pincode are not split up by the later steps.
    pincode, rest = extract_pincode(text or "")  # step 5 (done first so digits are not split)
    tokens = tokenize(rest)  # step 1
    tokens = expand_abbreviations(tokens)  # step 2
    # The gazetteer needs a district to look up aliases, so step 3 is skipped without one.
    if gazetteer is not None and district:
        tokens = gazetteer.canonicalise(district, tokens)  # step 3
    tokens = tamil_to_latin(tokens)  # step 4
    tokens = remove_stopwords(tokens)  # step 6
    core = remove_generic_words(tokens) if drop_generic else list(tokens)
    return NormalisedText(text or "", tuple(tokens), tuple(core), pincode)


def normalise_name(
    text: str, district: str | None = None, gazetteer: Gazetteer | None = None
) -> NormalisedText:
    """Normalise a property name or listing title (generic words removed in ``core``)."""
    return _normalise(text, drop_generic=True, district=district, gazetteer=gazetteer)


def normalise_address(
    text: str, district: str | None = None, gazetteer: Gazetteer | None = None
) -> NormalisedText:
    """Normalise an address or locality text (generic words kept; pincode extracted)."""
    return _normalise(text, drop_generic=False, district=district, gazetteer=gazetteer)
