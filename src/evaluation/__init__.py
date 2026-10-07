"""M5 matching evaluation harness (testing-and-evaluation.md §3). Pure Python, no Django.

This is the only code that reads ``ground_truth.csv``. The matcher (``src/matching``) never
imports this package (tested). All numbers it prints come from SYNTHETIC data and say
nothing about real-world accuracy (AGENTS.md rule 10).
"""
