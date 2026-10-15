"""One-command local start for development. Called by start.bat.

Who runs it: a developer on Windows, by double-clicking start.bat or running this file
from the project folder. Each step is safe to repeat.

Key idea: the script walks through a fixed list of checks and setup steps. It stops with
a clear message at the first problem, and only then starts the Django development server.

Steps:
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
# The server listens on localhost only, so other computers on the network cannot reach
# a development server that has DEBUG switched on.
HOST, PORT = "127.0.0.1", "8000"
URL = f"http://{HOST}:{PORT}/"

# Two synthetic demo accounts: an administrator and an officer for the Nilgiris district.
# Each entry is (username, extra arguments for the create_account command).
DEMO_ACCOUNTS = (
    ("demo_admin", ["--role", "admin"]),
    ("demo_officer_nilgiris", ["--role", "officer", "--district", "Nilgiris"]),
)

# Shown when PostgreSQL does not answer. It gives two options: a local install, or a free
# hosted database. The {url} placeholder is filled with the redacted connection string.
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
    """Print one progress line with a [start] prefix and flush it straight away.

    Flushing matters because the Django server may run for a long time and the lines must
    show up before it starts.
    """
    print(f"[start] {message}", flush=True)


def read_env(path: Path) -> dict[str, str]:
    """Read KEY=VALUE pairs from a file and return them as a dictionary.

    Blank lines and lines starting with # are skipped. A missing file gives an empty
    dictionary, so a first run without .env does not crash.
    """
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip("\"'")
    return values


def ensure_env_file() -> None:
    """Create .env from .env.example if it does not exist yet.

    The new file gets a fresh random secret key, debug mode on, and localhost-only hosts.
    The key is generated on this machine and is never committed.
    """
    if ENV_FILE.exists():
        return
    say("No .env found: creating one for local development (git-ignored).")
    lines = []
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        # Only these three lines change. Every other example setting is copied unchanged.
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
    """Return a copy of the environment for child processes, with .env values added.

    Variables already set in the shell win over .env, so a one-off override still works.
    """
    env = os.environ.copy()
    for key, value in read_env(ENV_FILE).items():
        env.setdefault(key, value)
    return env


def run(args: list[str], env: dict[str, str], capture: bool = False) -> subprocess.CompletedProcess:
    """Run this same Python interpreter with the given arguments, from the project root.

    Using sys.executable keeps the child on the project's .venv. With capture=True, stdout
    and stderr are returned instead of shown on screen. The call never raises on failure;
    callers check returncode.
    """
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=capture,
        check=False,
    )


def ensure_requirements(env: dict[str, str]) -> None:
    """Install requirements.txt, but only when Django, psycopg or rapidfuzz cannot be imported.

    The import check is quick, so a normal start does not reinstall packages every time.
    """
    probe = run(["-c", "import django, psycopg, rapidfuzz"], env, capture=True)
    if probe.returncode == 0:
        return
    say("Installing requirements into the existing .venv ...")
    if run(["-m", "pip", "install", "-r", "requirements.txt"], env).returncode != 0:
        sys.exit("[start] pip install failed.")


def database_reachable(env: dict[str, str]) -> bool:
    """Return True if PostgreSQL accepts a connection on DATABASE_URL.

    The test runs in a separate Python process, so this script does not need the database
    driver to be importable itself. The URL is passed as an argument, so it never appears
    in the code text. The process gives up after 5 seconds.
    """
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
    """Run src/manage.py with the given Django command and return the completed process."""
    return run([str(MANAGE), *args], env, capture=capture)


def registry_rows(env: dict[str, str]) -> int:
    """Return how many registry entries are in the database.

    The script exits with a message if Django cannot answer.
    """
    code = "from registry.models import RegistryEntry; print(RegistryEntry.objects.count())"
    result = manage(env, "shell", "-c", code, capture=True)
    if result.returncode != 0:
        sys.exit(f"[start] Could not read the registry:\n{result.stderr}")
    # The count is the last line. Earlier lines may hold Django startup messages.
    return int(result.stdout.strip().splitlines()[-1])


def existing_accounts() -> dict[str, str]:
    """Read saved demo accounts from .dev-accounts.txt as a username-to-password dictionary.

    Lines starting with # and lines without a colon are skipped. A missing file gives an
    empty dictionary.
    """
    accounts: dict[str, str] = {}
    if ACCOUNTS_FILE.exists():
        for line in ACCOUNTS_FILE.read_text(encoding="utf-8").splitlines():
            if ":" in line and not line.startswith("#"):
                name, _, password = line.partition(":")
                accounts[name.strip()] = password.strip()
    return accounts


def ensure_accounts(env: dict[str, str], reset: bool) -> None:
    """Create the two demo accounts that are missing, and save all their passwords.

    Passwords are random. They reach create_account through an environment variable, so
    they never appear on a command line. If an account exists but its password is not in
    the file, it is skipped, because the password cannot be recovered. With reset=True the
    saved passwords are ignored, so only accounts missing from the database get new ones.
    """
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
    """Open the tourist page in the browser after a short delay, in a background thread.

    The delay gives the development server time to start first. The thread is a daemon,
    so it never keeps the script running after the server stops.
    """

    def _open() -> None:
        """Wait for the delay, then open the URL in the default browser."""
        time.sleep(delay)
        webbrowser.open(URL)

    threading.Thread(target=_open, daemon=True).start()


def main(argv: list[str]) -> int:
    """Run every start-up step in order, then start the development server.

    Options: --reset-accounts writes new demo passwords, and --no-browser stops the
    browser from opening. Returns the server's exit code, or 1 if a step failed.
    """
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

    # Migrations must run before the cache table step, and both before any data is loaded.
    for step in (("migrate",), ("createcachetable",)):
        if manage(env, *step).returncode != 0:
            return 1

    # Load the synthetic data only on the first run. Later runs keep the data they have.
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
        # Ctrl+C is the normal way to stop the server, so it is not an error.
        return 0


def _redact(url: str) -> str:
    """Hide the password part of a database URL so it can be printed safely.

    The user name and password between "://" and "@" are replaced by ***. The host and
    database name stay visible. A URL without "@" is returned unchanged.
    """
    if "@" in url and "://" in url:
        scheme, _, rest = url.partition("://")
        return f"{scheme}://***@{rest.rpartition('@')[2]}"
    return url


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
