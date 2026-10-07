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
MANAGE = ROOT / "src" / "manage.py"
DOTENV = ROOT / ".env"


def read_dotenv(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE reader for the git-ignored .env (D31: no python-dotenv).
    Ignores blank lines and # comments; strips matching surrounding quotes."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _load_env() -> None:
    """Fill os.environ from .env without overriding variables already set."""
    for key, value in read_dotenv(DOTENV).items():
        os.environ.setdefault(key, value)


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


def _manage(*args: str) -> int:
    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is not set. Add it to .env (see .env.example and docs/progress.md).")
        return 2
    return _run(str(MANAGE), *args)


def migrate() -> int:
    return _manage("migrate")


def run() -> int:
    return _manage("runserver")


def load() -> int:
    """Load the committed M1 synthetic dev and test sets into the database (M2)."""
    return _manage("load_synthetic", "--set", "all")


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
    "run": run,
    "test": test,
    "lint": lint,
    "eval": _not_yet("eval", "M5"),
    "seed": seed,
    "migrate": migrate,
    "load": load,
}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in TARGETS:
        print(f"Usage: python tasks.py <{'|'.join(TARGETS)}>")
        return 2
    _load_env()
    return TARGETS[argv[1]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
