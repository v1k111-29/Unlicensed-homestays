"""CI eval gate: floors on DEV-set metrics (testing-and-evaluation.md §3, D55).

A "floor" is the lowest value a metric may have and still pass. "Gate" means the check that
stops a change from merging when a metric falls below its floor.

Floors sit a little below the tuned dev baseline, so a code change that makes matching on
the synthetic dev set clearly worse fails CI. They are regression guards on synthetic data,
not accuracy targets or claims (AGENTS.md rule 10). Change them only together with a new
params version and a decisions.md entry.
"""

from __future__ import annotations

from collections.abc import Mapping

from evaluation.metrics import Ratio

# metric name -> minimum value on the dev set (D55). Dev baseline with m5-tuned-1 is 1.000
# for every metric below [V, synthetic]. Each floor leaves room for a few dev listings to
# move (shown as "allows"), so harmless changes pass but a real regression fails.
# The count next to each floor is the number of dev listings the metric is computed over.
FLOORS: dict[str, float] = {
    "matched_precision": 0.98,  # 165 matched: allows 3 wrong entries (also the §3 target)
    "match_recall": 0.95,  # 165 clean + noisy: allows 8 to fall to review
    "no_counterpart_in_queue": 0.95,  # 54 listings: allows 2 matched (§3 target 0.95)
    "hard_negative_not_matched": 0.95,  # 45 listings: allows 2 matched
    "wrong_licence_high_priority": 0.95,  # 36 listings: allows 1 outside the licence band
    "blocking_recall": 0.98,  # 201 listings with a true entry: allows 4 not blocked
}


def check_gate(metrics: Mapping[str, Ratio], floors: Mapping[str, float] = FLOORS) -> list[str]:
    """Return one message per floor that is not met (empty list = gate passed).

    A metric that cannot be computed (0/0) or is missing fails: an empty set must not pass.
    """
    failures = []
    for name, floor in floors.items():
        ratio = metrics.get(name)
        # A missing or 0/0 metric counts as a failure. Otherwise an empty test set would pass
        # silently.
        if ratio is None or ratio.value is None:
            failures.append(f"{name}: not computable (floor {floor:.3f})")
        elif ratio.value < floor:
            failures.append(f"{name}: {ratio} below floor {floor:.3f}")
    return failures
