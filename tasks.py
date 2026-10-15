r"""Single source of project commands for Verified Stays. Standard library only.

Who runs it: the developer, from the repository root, on Windows. CI and the Dockerfile
also call it, through the thin Makefile.

Key idea: ``python tasks.py <target>`` looks the target name up in TARGETS, loads the
git-ignored .env file into the environment, and then calls the matching function.
Each function either runs a Django command through src/manage.py or runs another tool.
Commands are defined only here, so the Makefile never has to change.

Usage: python tasks.py <target>
Windows: .venv\Scripts\python.exe tasks.py <target>
"""

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

# The repository root is the folder that holds this file. Every other path is built from it,
# so the commands work no matter which folder you type them in.
ROOT = Path(__file__).resolve().parent
REQUIREMENTS = ROOT / "requirements-dev.txt"
MANAGE = ROOT / "src" / "manage.py"
DOTENV = ROOT / ".env"


def read_dotenv(path: Path) -> dict[str, str]:
    """Read KEY=VALUE pairs from a .env file and return them as a dictionary.

    Blank lines and lines starting with # are skipped. Matching single or double quotes
    around a value are removed. A missing file gives an empty dictionary.
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        # partition splits only at the first "=", so values may themselves contain "=".
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _load_env() -> None:
    """Copy values from .env into os.environ, without overwriting variables already set.

    A variable set in the shell wins over the same name in .env. That lets a developer
    override one value for a single command.
    """
    for key, value in read_dotenv(DOTENV).items():
        os.environ.setdefault(key, value)


def _in_venv_or_ci() -> bool:
    """Return True when the script runs inside a virtual environment or in CI.

    A venv makes sys.prefix differ from sys.base_prefix. CI usually has no venv, so the
    CI variable (set by GitHub Actions) is accepted as the other signal.
    """
    return sys.prefix != sys.base_prefix or bool(os.environ.get("CI"))


def _run(*args: str) -> int:
    """Run the current Python interpreter with the given arguments, from the repo root.

    Returns the child process exit code.
    """
    return subprocess.call([sys.executable, *args], cwd=ROOT)


def setup() -> int:
    """Install the development requirements into the current interpreter.

    It refuses to run outside a virtual environment, so packages never land in the global
    Python by accident. It never creates a venv.
    """
    if not _in_venv_or_ci():
        print(r"Run with the existing .venv interpreter: .venv\Scripts\python.exe tasks.py setup")
        return 2
    return _run("-m", "pip", "install", "-r", str(REQUIREMENTS))


def test() -> int:
    """Run the test suite with pytest."""
    return _run("-m", "pytest")


def lint() -> int:
    """Run ruff lint, then ruff format in check mode.

    The `or` runs the second check only when the first one returns 0. If lint fails, its
    failing exit code is returned straight away.
    """
    return _run("-m", "ruff", "check", ".") or _run("-m", "ruff", "format", "--check", ".")


def _manage(*args: str) -> int:
    """Run src/manage.py with the given Django command.

    Every database command needs DATABASE_URL, so the check happens first. Without it the
    function prints a hint and returns 2 without running Django.
    """
    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is not set. Add it to .env (see .env.example and docs/progress.md).")
        return 2
    return _run(str(MANAGE), *args)


def migrate() -> int:
    """Apply database migrations, then create the login throttle cache table."""
    # createcachetable: the login address throttle uses the database cache (D58).
    # The `or` skips the second command if migrate fails.
    return _manage("migrate") or _manage("createcachetable")


def run() -> int:
    """Start the Django development server."""
    return _manage("runserver")


def load() -> int:
    """Load the committed M1 synthetic dev and test sets into the database (M2)."""
    return _manage("load_synthetic", "--set", "all")


def seed() -> int:
    """Generate the synthetic dev and test data sets.

    The generator is deterministic, so the same seeds always give the same files. See the
    generator's module docstring for details.
    """
    return _run(str(ROOT / "data" / "synthetic" / "generator.py"))


def evaluate(*options: str) -> int:
    """Run the matching evaluation on the synthetic DEV set and apply the CI floors (M5).

    It does not need a database. Options are passed through to ``python -m evaluation``,
    for example ``--set test --final-test-run`` for the single, guarded test-set run
    (AGENTS.md rule 9).
    """
    return subprocess.call([sys.executable, "-m", "evaluation", *options], cwd=ROOT / "src")


def messages(*options: str) -> int:
    """Extract translatable strings and compile the Tamil catalogue.

    This runs in pure Python (src/config/catalog.py, D77), because GNU gettext is not
    installed on Windows here. Existing translations are kept.
    ``messages --check`` only reports a stale catalogue or a missing translation, with exit
    code 1.
    """
    command = "check" if "--check" in options else "update"
    return subprocess.call([sys.executable, "-m", "config.catalog", command], cwd=ROOT / "src")


# Maps each command name typed on the command line to the function that runs it.
TARGETS: dict[str, Callable[..., int]] = {
    "setup": setup,
    "run": run,
    "test": test,
    "lint": lint,
    "eval": evaluate,
    "seed": seed,
    "migrate": migrate,
    "load": load,
    "messages": messages,
}
# Targets that accept extra command-line options.
PASS_THROUGH = {"eval", "messages"}


def main(argv: list[str]) -> int:
    """Check the command line, load .env, and run the chosen target.

    argv[0] is the script name, argv[1] the target, and anything after it is passed on.
    Returns 2 for a usage error (no target, an unknown target, or extra arguments to a
    target that takes none).
    """
    # The usage check comes first so a typo is reported before .env is read.
    if len(argv) < 2 or argv[1] not in TARGETS or (len(argv) > 2 and argv[1] not in PASS_THROUGH):
        print(f"Usage: python tasks.py <{'|'.join(TARGETS)}>  (eval also takes --help)")
        return 2
    # Load .env before any target runs, so every target sees DATABASE_URL and the other
    # settings.
    _load_env()
    return TARGETS[argv[1]](*argv[2:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
