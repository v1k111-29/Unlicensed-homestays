"""Metric computation for the matching evaluation (testing-and-evaluation.md §3).

Pure functions over plain rows: easy to test on tiny hand-built cases. Ground truth enters
here as ``Truth`` rows read by ``read_truth``; the matcher never sees it.

Key terms:
- A "listing" is one online homestay record. The "truth" says which registry entry it really
  belongs to, if any.
- A "band" is the matcher's verdict for a listing (for example matched, review or no match).
  ``STATUS`` maps each band to a status.
- A "metric" is a ratio: how many listings passed a test, out of how many were tested.
- The "review queue" holds the listings an officer must look at: everything that is not
  "Matched".

Every number is a result on SYNTHETIC data only. It is not a real-world accuracy figure
(AGENTS.md rule 10).
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from matching.engine import BANDS, STATUS, Outcome

# Ground-truth listing types (synthetic-data-spec.md "Listing types").
CLEAN = "clean"
NOISY = "noisy"
WRONG_OR_EXPIRED = "wrong_or_expired"
NO_COUNTERPART = "no_counterpart"
HARD_NEGATIVE = "hard_negative"
TYPES = (CLEAN, NOISY, WRONG_OR_EXPIRED, NO_COUNTERPART, HARD_NEGATIVE)
# Listings whose correct outcome is "Matched" to their true entry.
POSITIVE_TYPES = (CLEAN, NOISY)

# Reason codes added by gates beyond the §7 band table (Q21, D53). A "gate" is an extra check
# that can send a listing to review even when its band alone would have matched it.
GATE_REASONS = (
    "several_similar",
    "name_differs",
    "licence_name_differs",
    "licence_locality_differs",
)


@dataclass(frozen=True)
class Truth:
    """The answer key for one listing: its true registry entry (if any) and its noise tags."""

    listing_id: str
    true_registry_id: str | None
    type: str
    noise: tuple[str, ...] = ()


@dataclass(frozen=True)
class Row:
    """One listing: what the engine said, next to what the synthetic truth says."""

    listing_id: str
    type: str
    noise: tuple[str, ...]
    true_registry_id: str | None
    band: str
    reasons: tuple[str, ...]
    top_registry_id: str | None  # entry the band refers to (None for no_candidate)
    candidate_ids: tuple[str, ...]  # stored candidates, best first

    @property
    def status(self) -> str:
        """The status of this listing's band, such as "matched"."""
        return STATUS[self.band]

    @property
    def matched(self) -> bool:
        """True when the engine marked this listing as matched to some entry."""
        return self.status == "matched"

    @property
    def in_queue(self) -> bool:
        """Needs review or no match: the listing reaches an officer's review queue."""
        return not self.matched

    @property
    def matched_correctly(self) -> bool:
        """True when the listing is matched and the entry it matched is its true entry."""
        return (
            self.matched
            and self.true_registry_id is not None
            and (self.top_registry_id == self.true_registry_id)
        )


@dataclass(frozen=True)
class Ratio:
    """A count out of a count, such as 3 of 4. Keeps both numbers so a report can show them.

    When the denominator is 0 (no listing qualified), ``value`` is None instead of a division
    error, and the metric counts as "not computable" (see gate.check_gate).
    """

    num: int
    den: int

    @property
    def value(self) -> float | None:
        """The ratio as a decimal, or None when the denominator is 0."""
        return None if self.den == 0 else self.num / self.den

    def __str__(self) -> str:
        """For example "0.947 (18/19)", or "n/a (0/0)" when nothing qualified."""
        if self.den == 0:
            return "n/a (0/0)"
        return f"{self.value:.3f} ({self.num}/{self.den})"


def read_truth(path: Path | str) -> dict[str, Truth]:
    """Read ``ground_truth.csv``: listing_id, true_registry_id, type, noise (';'-joined)."""
    out: dict[str, Truth] = {}
    # utf-8-sig drops a BOM if the file has one. newline="" lets the csv module handle line ends.
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["type"] not in TYPES:
                raise ValueError(f"{path}: unknown listing type {r['type']!r}")
            # Noise tags are stored as one cell joined with ";". Empty pieces are dropped.
            noise = tuple(n for n in (r.get("noise") or "").split(";") if n)
            out[r["listing_id"]] = Truth(
                listing_id=r["listing_id"],
                true_registry_id=r["true_registry_id"] or None,  # empty cell means no entry
                type=r["type"],
                noise=noise,
            )
    return out


def join(outcomes: Iterable[Outcome], truth: Mapping[str, Truth]) -> list[Row]:
    """Pair every engine outcome with its truth row. Both sides must cover the same ids."""
    rows = []
    seen = set()
    for o in outcomes:
        key = str(o.listing_id)
        if key not in truth:
            raise ValueError(f"no ground truth for listing {key}")
        seen.add(key)
        t = truth[key]
        rows.append(
            Row(
                listing_id=key,
                type=t.type,
                noise=t.noise,
                true_registry_id=t.true_registry_id,
                band=o.band,
                reasons=tuple(o.reasons),
                top_registry_id=None if o.top_registry_id is None else str(o.top_registry_id),
                candidate_ids=tuple(str(c.registry_id) for c in o.candidates),
            )
        )
    # Every truth row must also have an outcome. Otherwise a listing would be left out of the
    # metrics without anyone noticing.
    missing = set(truth) - seen
    if missing:
        raise ValueError(f"{len(missing)} truth rows have no outcome, e.g. {sorted(missing)[0]}")
    return rows


def _ratio(rows: Sequence[Row], hit: Callable[[Row], bool]) -> Ratio:
    """Count the rows for which ``hit`` is True, out of all the rows given."""
    return Ratio(sum(1 for r in rows if hit(r)), len(rows))


def compute_metrics(rows: Sequence[Row]) -> dict[str, Ratio]:
    """Headline metrics (testing-and-evaluation.md §3), each as a ``Ratio``.

    - matched_precision: of listings the engine marks "Matched", share matched to their true
      registry entry.
    - match_recall: of clean + noisy listings (a true entry exists), share "Matched" to it.
    - no_counterpart_in_queue: of listings with no registry entry, share that reach the review
      queue (not "Matched").
    - hard_negative_not_matched: of hard negatives (same locality, different property), share
      not "Matched" to anything.
    - wrong_licence_high_priority: of listings with a wrong or lapsed licence, share in the
      high-priority licence review band.
    - positive_top_candidate: of clean + noisy listings, share whose best candidate is the
      true entry (whatever the band) - what an officer sees first.
    - blocking_recall: of listings with a true entry, share whose true entry was a candidate.
    - review_queue_share: share of all listings that reach the review queue (workload).
    """
    # Group the rows by listing type once, so each per-type metric reads its own group.
    by_type: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_type[r.type].append(r)
    positives = [r for r in rows if r.type in POSITIVE_TYPES]
    with_truth = [r for r in rows if r.true_registry_id is not None]
    matched = [r for r in rows if r.matched]
    return {
        "matched_precision": _ratio(matched, lambda r: r.matched_correctly),
        "match_recall": _ratio(positives, lambda r: r.matched_correctly),
        "no_counterpart_in_queue": _ratio(by_type[NO_COUNTERPART], lambda r: r.in_queue),
        "hard_negative_not_matched": _ratio(by_type[HARD_NEGATIVE], lambda r: not r.matched),
        "wrong_licence_high_priority": _ratio(
            by_type[WRONG_OR_EXPIRED], lambda r: r.band == "review_licence"
        ),
        "positive_top_candidate": _ratio(
            positives,
            lambda r: bool(r.candidate_ids) and r.candidate_ids[0] == r.true_registry_id,
        ),
        "blocking_recall": _ratio(with_truth, lambda r: r.true_registry_id in r.candidate_ids),
        "review_queue_share": _ratio(rows, lambda r: r.in_queue),
    }


def workload(rows: Sequence[Row]) -> dict[str, int]:
    """Review-queue size and what it is made of."""
    queue = [r for r in rows if r.in_queue]
    return {
        "listings": len(rows),
        "queue": len(queue),
        "queue_true_counterpart": sum(1 for r in queue if r.type in POSITIVE_TYPES),
        "queue_other": sum(1 for r in queue if r.type not in POSITIVE_TYPES),
        "matched": len(rows) - len(queue),
        "matched_wrong_entry": sum(1 for r in rows if r.matched and not r.matched_correctly),
        "positive_no_candidate": sum(
            1 for r in rows if r.type in POSITIVE_TYPES and r.band == "no_candidate"
        ),
    }


def group_labels(row: Row) -> list[str]:
    """Rows of the confusion matrix this listing counts in.

    Noisy listings count once in ``noisy (all)`` and once under each noise template they
    carry, so template rows can overlap.
    """
    if row.type != NOISY:
        return [row.type]
    return ["noisy (all)"] + [f"noisy:{n}" for n in row.noise]


WRONG_ENTRY = "matched_wrong_entry"  # extra column: matched, but to the wrong registry entry
CONFUSION_COLUMNS = (*BANDS, WRONG_ENTRY)


def confusion(rows: Sequence[Row]) -> dict[str, Counter]:
    """Listing type / noise template x band. A "Matched" listing whose entry is not its true
    entry is counted in ``matched_wrong_entry`` instead of its band."""
    table: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        col = WRONG_ENTRY if r.matched and not r.matched_correctly else r.band
        for label in group_labels(r):
            table[label][col] += 1
    # The rows are listed in a fixed order, so the printed matrix reads the same on every run:
    # clean, the noisy total, the noise templates in alphabetical order, then the other types.
    order = [CLEAN, "noisy (all)"]
    order += sorted(k for k in table if k.startswith("noisy:"))
    order += [WRONG_OR_EXPIRED, NO_COUNTERPART, HARD_NEGATIVE]
    return {k: table[k] for k in order if k in table}


def gate_effects(rows: Sequence[Row]) -> dict[str, dict[str, int]]:
    """How many listings each extra gate sends to review (Q21), split by listing type."""
    out: dict[str, dict[str, int]] = {}
    for reason in GATE_REASONS:
        hit = [r for r in rows if reason in r.reasons]
        out[reason] = dict(sorted(Counter(r.type for r in hit).items()))
    return out
