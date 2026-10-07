r"""Single source of project commands. Standard library only.

Usage: python tasks.py <target>
Windows: .venv\Scripts\python.exe tasks.py <target>
"""

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIREMENTS = ROOT / "requirements-dev.txt"


def _in_venv_or_ci() -> bool:
    return sys.prefix != sys.base_prefix or bool(os.environ.get("CI"))


def _run(*args: str) -> int:
    return subprocess.call([sys.executable, *args], cwd=ROOT)


def setup() -> int:
    """Install deps into the current interpreter. Never creates a venv."""
    if not _in_venv_or_ci():
        print(r"Run with the existing .venv interpreter: .venv\Scripts\python.exe tasks.py setup")
        return 2
    return _run("-m", "pip", "install", "-r", str(REQUIREMENTS))


def test() -> int:
    return _run("-m", "pytest")


def lint() -> int:
    return _run("-m", "ruff", "check", ".") or _run("-m", "ruff", "format", "--check", ".")


def seed() -> int:
    """Generate the synthetic dev/test data sets (deterministic; see generator docstring)."""
    return _run(str(ROOT / "data" / "synthetic" / "generator.py"))


def _not_yet(target: str, module: str) -> Callable[[], int]:
    def command() -> int:
        print(f"'{target}' is not implemented until {module}.")
        return 2

    return command


TARGETS: dict[str, Callable[[], int]] = {
    "setup": setup,
    "run": _not_yet("run", "M2"),
    "test": test,
    "lint": lint,
    "eval": _not_yet("eval", "M5"),
    "seed": seed,
    "migrate": _not_yet("migrate", "M2"),
}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in TARGETS:
        print(f"Usage: python tasks.py <{'|'.join(TARGETS)}>")
        return 2
    return TARGETS[argv[1]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
