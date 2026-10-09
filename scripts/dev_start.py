"""One-command local start for development (called by start.bat).

Steps, each safe to repeat:
  1. create a git-ignored .env for local work if none exists (DEBUG on, random secret key);
  2. install requirements if Django is missing;
  3. check that PostgreSQL answers on DATABASE_URL, else print how to fix it and stop;
  4. migrate + create the cache table;
  5. load the synthetic dev + test sets once (skipped when the registry already has rows);
  6. create two local demo accounts once; passwords are random and kept in .dev-accounts.txt
     (git-ignored). Synthetic demo accounts only: no real people (AGENTS.md rule 3);
  7. start the Django development server and open the browser.

Standard library only. Never commits or prints secrets other than the local demo passwords.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANAGE = ROOT / "src" / "manage.py"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
ACCOUNTS_FILE = ROOT / ".dev-accounts.txt"
HOST, PORT = "127.0.0.1", "8000"
URL = f"http://{HOST}:{PORT}/"

DEMO_ACCOUNTS = (
    ("demo_admin", ["--role", "admin"]),
    ("demo_officer_nilgiris", ["--role", "officer", "--district", "Nilgiris"]),
)

POSTGRES_HELP = """
PostgreSQL is not reachable with the DATABASE_URL in .env:
  {url}

Pick ONE:
  A) Local PostgreSQL (free):
       winget install PostgreSQL.PostgreSQL.16
     then, in "SQL Shell (psql)" as the postgres user:
       CREATE ROLE verified_stays LOGIN PASSWORD 'choose-a-password';
       CREATE DATABASE verified_stays OWNER verified_stays;
     and put the same password in DATABASE_URL in .env:
       DATABASE_URL=postgres://verified_stays:choose-a-password@localhost:5432/verified_stays
  B) Hosted free database (no install): create a Neon project (docs/deploy-runbook.md
     section 2) and paste its DIRECT connection string into DATABASE_URL in .env.
     Use a separate Neon branch/database for development, not the demo one.

Then run start.bat again.
"""


def say(message: str) -> None:
    print(f"[start] {message}", flush=True)


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip("\"'")
    return values


def ensure_env_file() -> None:
    if ENV_FILE.exists():
        return
    say("No .env found: creating one for local development (git-ignored).")
    lines = []
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        if line.startswith("DJANGO_SECRET_KEY="):
            line = f"DJANGO_SECRET_KEY={secrets.token_urlsafe(64)}"
        elif line.startswith("DJANGO_DEBUG="):
            line = "DJANGO_DEBUG=1"
        elif line.startswith("DJANGO_ALLOWED_HOSTS="):
            line = "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1"
        lines.append(line)
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    say("Wrote .env. Edit DATABASE_URL in it if your PostgreSQL password differs.")


def child_env() -> dict[str, str]:
    env = os.environ.copy()
    for key, value in read_env(ENV_FILE).items():
        env.setdefault(key, value)
    return env


def run(args: list[str], env: dict[str, str], capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=capture,
        check=False,
    )


def ensure_requirements(env: dict[str, str]) -> None:
    probe = run(["-c", "import django, psycopg, rapidfuzz"], env, capture=True)
    if probe.returncode == 0:
        return
    say("Installing requirements into the existing .venv ...")
    if run(["-m", "pip", "install", "-r", "requirements.txt"], env).returncode != 0:
        sys.exit("[start] pip install failed.")


def database_reachable(env: dict[str, str]) -> bool:
    url = env.get("DATABASE_URL", "")
    if not url:
        return False
    code = (
        "import sys, psycopg\n"
        "try:\n"
        "    psycopg.connect(sys.argv[1], connect_timeout=5).close()\n"
        "except Exception as exc:\n"
        "    print(type(exc).__name__)\n"
        "    sys.exit(1)\n"
    )
    result = run(["-c", code, url], env, capture=True)
    return result.returncode == 0


def manage(env: dict[str, str], *args: str, capture: bool = False) -> subprocess.CompletedProcess:
    return run([str(MANAGE), *args], env, capture=capture)


def registry_rows(env: dict[str, str]) -> int:
    code = "from registry.models import RegistryEntry; print(RegistryEntry.objects.count())"
    result = manage(env, "shell", "-c", code, capture=True)
    if result.returncode != 0:
        sys.exit(f"[start] Could not read the registry:\n{result.stderr}")
    return int(result.stdout.strip().splitlines()[-1])


def existing_accounts() -> dict[str, str]:
    accounts: dict[str, str] = {}
    if ACCOUNTS_FILE.exists():
        for line in ACCOUNTS_FILE.read_text(encoding="utf-8").splitlines():
            if ":" in line and not line.startswith("#"):
                name, _, password = line.partition(":")
                accounts[name.strip()] = password.strip()
    return accounts


def ensure_accounts(env: dict[str, str], reset: bool) -> None:
    known = {} if reset else existing_accounts()
    check = (
        "from accounts.models import User; print(*User.objects.values_list('username', flat=True))"
    )
    listed = manage(env, "shell", "-c", check, capture=True)
    present = set(listed.stdout.split()) if listed.returncode == 0 else set()
    created = dict(known)
    for username, extra in DEMO_ACCOUNTS:
        if username in present and username in known:
            continue
        if username in present:
            say(f"Account {username} exists but its password is not on file; skipped.")
            continue
        password = secrets.token_urlsafe(14)
        account_env = {**env, "DEMO_ACCOUNT_PASSWORD": password}
        done = manage(
            account_env,
            "create_account",
            username,
            *extra,
            "--password-env",
            "DEMO_ACCOUNT_PASSWORD",
        )
        if done.returncode == 0:
            created[username] = password
            say(f"Created demo account {username}.")
    lines = ["# Local demo accounts (synthetic, development only). Git-ignored."]
    lines += [f"{name}: {password}" for name, password in created.items()]
    ACCOUNTS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def open_browser_later(delay: float = 3.0) -> None:
    def _open() -> None:
        time.sleep(delay)
        webbrowser.open(URL)

    threading.Thread(target=_open, daemon=True).start()


def main(argv: list[str]) -> int:
    os.chdir(ROOT)
    ensure_env_file()
    env = child_env()
    if env.get("DJANGO_DEBUG") != "1":
        say("Warning: DJANGO_DEBUG is not 1 in .env; the dev server needs HTTPS settings then.")
    ensure_requirements(env)

    if not database_reachable(env):
        print(POSTGRES_HELP.format(url=_redact(env.get("DATABASE_URL", "(not set)"))))
        return 1
    say("Database reachable.")

    for step in (("migrate",), ("createcachetable",)):
        if manage(env, *step).returncode != 0:
            return 1

    if registry_rows(env) == 0:
        say("Loading synthetic dev and test sets (first run only) ...")
        if manage(env, "load_synthetic", "--set", "all").returncode != 0:
            return 1
    else:
        say("Synthetic data already loaded.")

    ensure_accounts(env, reset="--reset-accounts" in argv)

    print()
    say(f"Tourist page : {URL}")
    say(f"Officer login: {URL}login/")
    say(f"Demo accounts and passwords: {ACCOUNTS_FILE.name} (local file, git-ignored)")
    say("Stop the server with Ctrl+C. All data is synthetic demonstration data.")
    print()
    if "--no-browser" not in argv:
        open_browser_later()
    try:
        return manage(env, "runserver", f"{HOST}:{PORT}").returncode
    except KeyboardInterrupt:
        return 0


def _redact(url: str) -> str:
    if "@" in url and "://" in url:
        scheme, _, rest = url.partition("://")
        return f"{scheme}://***@{rest.rpartition('@')[2]}"
    return url


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
