"""Threshold tuning aid. DEV SET ONLY (AGENTS.md rule 9): there is no option to read test.

``python -m evaluation.tune`` (from ``src``) prints, for the dev set:
1. score margins: how far true pairs and false pairs sit from each threshold;
2. a grid over the band thresholds with the dev metrics of every point.

A "threshold" is a cut-off number: a pair scoring above it counts as a possible match.
"Tuning" means choosing thresholds that give the best dev metrics. It must never be done on
the test set, because then the test set stops being an honest check.

How it was used for ``m5-tuned-1`` is recorded in docs/decisions.md (D55). Synthetic data
only; nothing here is a real-world accuracy figure (AGENTS.md rule 10).
"""

from __future__ import annotations

import itertools
import sys
from dataclasses import replace

from evaluation.harness import AS_OF, DATA
from evaluation.metrics import HARD_NEGATIVE, NO_COUNTERPART, POSITIVE_TYPES, compute_metrics, join
from evaluation.metrics import read_truth as _read_truth
from matching.engine import Outcome, match
from matching.gazetteer import Gazetteer
from matching.params import CURRENT_VERSION, MatchParams, get_params
from matching.records import listing_records_from_csv, registry_records_from_csv

DEV = DATA / "dev"  # the only set this module reads


def dev_outcomes(params: MatchParams, gaz: Gazetteer) -> list[Outcome]:
    """Run the matcher on the dev set only and return its raw outcomes."""
    return match(
        listing_records_from_csv(DEV / "listings.csv"),
        registry_records_from_csv(DEV / "registry.csv"),
        params,
        as_of=AS_OF,
        gazetteer=gaz,
    )


def _fmt(values: list[float]) -> str:
    """Summarise a list of numbers as "n=..., min=..., max=...", or "-" when it is empty."""
    if not values:
        return "-"
    return f"n={len(values)} min={min(values):.4f} max={max(values):.4f}"


def margins(params: MatchParams, gaz: Gazetteer) -> dict[str, str]:
    """Score / name values of true pairs and of the best false pair, split by path.

    A "path" is the way the matcher found a candidate: the score path (fuzzy name and
    locality similarity) or the licence path (an exact licence number match).
    """
    # Keep every candidate, not only the first few the engine stores, so the margins see the
    # whole field.
    wide = replace(params, max_stored_candidates=10_000)
    truth = _read_truth(DEV / "ground_truth.csv")
    # Listings that already quote a licence number. The score-path numbers below skip them, so
    # they only describe listings without a claimed licence.
    claims = {
        str(x.id): bool(x.claimed_licence_no)
        for x in listing_records_from_csv(DEV / "listings.csv")
    }
    out: dict[str, list[float]] = {
        "score path, true pair: score": [],
        "score path, true pair: name": [],
        "score path, true pair: lead over 2nd": [],
        "score path, no-entry listings: best score": [],
        "score path, no-entry listings: name of best if >= T_low": [],
        "licence path, true pair (valid): name": [],
        "licence path, other property's licence: name": [],
    }
    for o in dev_outcomes(wide, gaz):
        t = truth[str(o.listing_id)]
        cands = list(o.candidates)
        claimed = claims[str(o.listing_id)]
        if t.type in POSITIVE_TYPES and not claimed:
            true = next(c for c in cands if str(c.registry_id) == t.true_registry_id)
            others = [c.score for c in cands if c is not true]
            out["score path, true pair: score"].append(true.score)
            out["score path, true pair: name"].append(true.features["name"])
            # "Lead" is how far the true pair's score is above the next best candidate.
            out["score path, true pair: lead over 2nd"].append(
                round(true.score - max(others, default=0.0), 4)
            )
        elif t.type in (NO_COUNTERPART, HARD_NEGATIVE) and not claimed and cands:
            out["score path, no-entry listings: best score"].append(cands[0].score)
            if cands[0].score >= params.t_low:
                out["score path, no-entry listings: name of best if >= T_low"].append(
                    cands[0].features["name"]
                )
        # The first candidate that was blocked by the licence path, if any.
        hit = next((c for c in cands if "licence" in c.blocked_by), None)
        # A licence feature of exactly 1.0 means the licence number matched exactly.
        if hit is not None and hit.features["licence"] == 1.0:
            if t.type in POSITIVE_TYPES:
                out["licence path, true pair (valid): name"].append(hit.features["name"])
            elif str(hit.registry_id) != t.true_registry_id:
                out["licence path, other property's licence: name"].append(hit.features["name"])
    return {k: _fmt(v) for k, v in out.items()}


# The threshold values to try. Each tuple is one axis of the grid.
GRID = {
    "t_low": (0.65, 0.70, 0.75, 0.80),
    "t_high": (0.80, 0.85, 0.90, 0.95),
    "score_name_min": (0.75, 0.80, 0.85, 0.90),
}


def grid(params: MatchParams, gaz: Gazetteer) -> list[tuple[dict, dict]]:
    """Run the matcher once per threshold combination and return each point's dev metrics.

    A combination is skipped when t_low is not below t_high, because the bands would overlap.
    """
    truth = _read_truth(DEV / "ground_truth.csv")
    rows = []
    keys = list(GRID)
    # itertools.product gives every combination of the grid values, in a fixed order.
    for values in itertools.product(*(GRID[k] for k in keys)):
        point = dict(zip(keys, values, strict=True))
        if point["t_low"] >= point["t_high"]:
            continue
        p = replace(params, **point)
        m = compute_metrics(join(dev_outcomes(p, gaz), truth))
        rows.append((point, {k: r.value for k, r in m.items()}))
    return rows


def main() -> int:
    """Print the margins and the grid for the params version given on the command line.

    With no argument it uses the current version. Always returns 0.
    """
    params = get_params(sys.argv[1] if len(sys.argv) > 1 else CURRENT_VERSION)
    gaz = Gazetteer.load()
    print(f"DEV set only (synthetic). params {params.version}")
    print("Margins:")
    for k, v in margins(params, gaz).items():
        print(f"  {k:<58} {v}")
    print("\nGrid (precision / recall / no-counterpart in queue / hard-neg not matched / queue):")
    for point, m in grid(params, gaz):
        print(
            "  "
            + " ".join(f"{k}={v:.2f}" for k, v in point.items())
            + f"  P={m['matched_precision']:.3f} R={m['match_recall']:.3f}"
            f" NC={m['no_counterpart_in_queue']:.3f} HN={m['hard_negative_not_matched']:.3f}"
            f" Q={m['review_queue_share']:.3f}"
        )
    print("\nSYNTHETIC DATA ONLY; not a real-world accuracy figure.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
