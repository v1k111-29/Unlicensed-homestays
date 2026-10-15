"""CLI: ``python -m evaluation`` (run from ``src``) or ``python tasks.py eval [options]``.

    eval                                 dev set, metrics + CI gate (exit 1 below a floor)
    eval --params m4-initial-1           dev set with an older published params version
    eval --no-gate                       dev set, metrics only
    eval --set test --final-test-run     the single test-set run (refused if already done)

Synthetic data only; no real-world accuracy claim (AGENTS.md rule 10).
"""

# The first line of the docstring above is the help text that argparse shows for this command,
# so keep it short. Changing it changes the command's --help output.

from __future__ import annotations

import argparse
import sys

from evaluation.harness import SetGuardError, run_dev, run_test_set
from matching.params import CURRENT_VERSION, PARAMS


def main(argv: list[str] | None = None) -> int:
    """Parse the command-line options and run the dev or test set.

    Exit codes: 0 means success, 1 means a dev floor was missed, 2 means the test set was
    asked for with an old params version, and 3 means the test set run was refused.
    ``argv`` is the list of options; None means read them from the command line.
    """
    # The description is the first line of this module's docstring, so the help matches it.
    parser = argparse.ArgumentParser(prog="tasks.py eval", description=__doc__.split("\n")[0])
    parser.add_argument("--set", choices=("dev", "test"), default="dev")
    parser.add_argument("--params", choices=sorted(PARAMS), default=CURRENT_VERSION)
    parser.add_argument("--no-gate", action="store_true", help="dev only: skip the CI floors")
    parser.add_argument(
        "--final-test-run",
        action="store_true",
        help="required for --set test; allowed once, then recorded and refused",
    )
    args = parser.parse_args(argv)

    if args.set == "dev":
        return run_dev(args.params, gate=not args.no_gate)
    # The test set is only ever run with the current parameters, so no older version can be
    # tuned against it.
    if args.params != CURRENT_VERSION:
        print("The test set only runs with the current params version.")
        return 2
    try:
        return run_test_set(final=args.final_test_run)
    except SetGuardError as exc:
        print(f"REFUSED: {exc}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
