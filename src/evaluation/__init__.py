"""M5 matching evaluation harness (testing-and-evaluation.md §3). Pure Python, no Django.

The package measures how well the matcher (``src/matching``) does on the synthetic data sets.
It works by running the matcher, comparing each result with the answer key
(``ground_truth.csv``), and computing the metrics. Modules:

- ``metrics``: the metric functions, pure and easy to test on hand-made rows.
- ``harness``: runs one set and prints the report; also guards the test set.
- ``gate``: the CI floors that fail the build when a dev metric drops too far.
- ``tune``: a dev-only aid for choosing thresholds.
- ``__main__``: the command-line entry point.

This is the only code that reads ``ground_truth.csv``. The matcher (``src/matching``) never
imports this package (tested). All numbers it prints come from SYNTHETIC data and say
nothing about real-world accuracy (AGENTS.md rule 10).
"""
