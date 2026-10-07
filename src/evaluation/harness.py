"""Run the matcher on a synthetic set, score it against ground truth, print a report.

``python tasks.py eval`` runs the DEV set and applies the CI floor (``gate.FLOORS``).
The TEST set is run once, at the end of tuning, and is guarded (see ``run_test_set``):
AGENTS.md rule 9.

DB-free: records come from the committed CSVs (``matching.records``) and outcomes from
``matching.engine.match``. Results are on SYNTHETIC data only; they do not predict
real-world accuracy (AGENTS.md rule 10).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from evaluation.gate import FLOORS, check_gate
from evaluation.metrics import (
    CONFUSION_COLUMNS,
    Ratio,
    Row,
    compute_metrics,
    confusion,
    gate_effects,
    join,
    read_truth,
    workload,
)
from matching.engine import match
from matching.gazetteer import Gazetteer
from matching.params import CURRENT_VERSION, MatchParams, get_params
from matching.records import listing_records_from_csv, registry_records_from_csv

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "synthetic" / "out"
SETS = ("dev", "test")
# Licence validity date for the synthetic sets: the generator's REFERENCE_DATE (D54).
AS_OF = date(2026, 4, 1)
# Committed record of the single test-set run (AGENTS.md rule 9). Its presence blocks reruns.
TEST_RUN_RECORD = ROOT / "docs" / "eval-test-run.json"

CAVEAT = (
    "SYNTHETIC DATA ONLY. These numbers show the method behaves as designed on fictional "
    "data; they do not predict real-world accuracy. Dev and test share districts and "
    "gazetteer, so the test set is not fully independent (D22)."
)


@dataclass(frozen=True)
class Report:
    set_name: str
    params: MatchParams
    rows: list[Row]
    metrics: dict[str, Ratio]


def evaluate(
    set_name: str,
    params: MatchParams | None = None,
    *,
    data_dir: Path = DATA,
    gazetteer: Gazetteer | None = None,
) -> Report:
    """Match one synthetic set and score it. Callers must guard the test set themselves."""
    if set_name not in SETS:
        raise ValueError(f"unknown set {set_name!r}")
    params = params or get_params()
    folder = data_dir / set_name
    listings = listing_records_from_csv(folder / "listings.csv")
    registry = registry_records_from_csv(folder / "registry.csv")
    outcomes = match(
        listings, registry, params, as_of=AS_OF, gazetteer=gazetteer or Gazetteer.load()
    )
    rows = join(outcomes, read_truth(folder / "ground_truth.csv"))
    return Report(set_name, params, rows, compute_metrics(rows))


def format_report(report: Report) -> str:
    p = report.params
    lines = [
        "=" * 78,
        f"Matching evaluation - {report.set_name.upper()} set (synthetic)",
        f"params {p.version} (fingerprint {p.fingerprint()}), as_of {AS_OF.isoformat()}",
        f"T_low {p.t_low}  T_high {p.t_high}  ambiguity {p.ambiguity_margin}  "
        f"name gates: licence {p.licence_name_min}, score {p.score_name_min}",
        "-" * 78,
        "Headline metrics:",
    ]
    for name, ratio in report.metrics.items():
        lines.append(f"  {name:<30} {ratio}")
    lines += ["", "Review workload:"]
    for name, n in workload(report.rows).items():
        lines.append(f"  {name:<30} {n}")
    lines += ["", "Confusion matrix (listing type / noise template x band):"]
    short = {
        "review_licence": "rev_lic",
        "no_candidate": "no_cand",
        "review_score": "rev_scr",
        "matched_score": "m_score",
        "matched_licence": "m_lic",
        "matched_confirmed": "m_conf",
        "matched_wrong_entry": "m_WRONG",
    }
    lines.append(f"  {'':<24}" + "".join(f"{short[c]:>8}" for c in CONFUSION_COLUMNS))
    for label, counts in confusion(report.rows).items():
        cells = "".join(f"{counts.get(c, 0):>8}" for c in CONFUSION_COLUMNS)
        lines.append(f"  {label:<24}{cells}")
    lines += ["", "Extra gates (Q21): listings sent to review by each reason, by type:"]
    for reason, by_type in gate_effects(report.rows).items():
        lines.append(f"  {reason:<30} {by_type or '-'}")
    lines += ["-" * 78, CAVEAT, "=" * 78]
    return "\n".join(lines)


def metrics_json(report: Report) -> dict:
    return {
        name: {"num": r.num, "den": r.den, "value": r.value} for name, r in report.metrics.items()
    }


# ----------------------------------------------------------------- dev + gate


def run_dev(params_version: str = CURRENT_VERSION, *, gate: bool = True) -> int:
    report = evaluate("dev", get_params(params_version))
    print(format_report(report))
    if not gate:
        return 0
    failures = check_gate(report.metrics)
    if failures:
        print("EVAL GATE FAILED (dev, synthetic):")
        for f in failures:
            print(f"  {f}")
        return 1
    print(f"Eval gate passed: {len(FLOORS)} floors met on the dev set (synthetic).")
    return 0


# ------------------------------------------------------------ test-set guard


class SetGuardError(RuntimeError):
    """Raised when the test set would be run without the explicit flag, or a second time."""


def run_test_set(*, final: bool, record: Path = TEST_RUN_RECORD, data_dir: Path = DATA) -> int:
    """Run the TEST set once (AGENTS.md rule 9).

    Needs ``final=True`` (``--final-test-run``). Refused if ``record`` already exists: the
    test set has been used and must not drive any more tuning. The record is committed.
    """
    if not final:
        raise SetGuardError(
            "The test set is run once, after tuning on dev (AGENTS.md rule 9). "
            "Pass --final-test-run to do that single run."
        )
    if record.exists():
        raise SetGuardError(
            f"The test set was already run (record: {record.name}). It must not be run again; "
            "a new run would turn it into a tuning set. See docs/testing-and-evaluation.md §3."
        )
    params = get_params(CURRENT_VERSION)
    report = evaluate("test", params, data_dir=data_dir)
    payload = {
        "set": "test",
        "synthetic": True,
        "caveat": CAVEAT,
        "params_version": params.version,
        "params_fingerprint": params.fingerprint(),
        "as_of": AS_OF.isoformat(),
        "run_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "metrics": metrics_json(report),
        "workload": workload(report.rows),
    }
    # Write the record before printing, so a crash while printing cannot allow a rerun.
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(format_report(report))
    print(f"Test-set run recorded in {record.name}. Do not tune on these numbers.")
    return 0
