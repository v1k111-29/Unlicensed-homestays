"""M11: health endpoints, production settings, security headers, log scrubbing, and static
checks of the deploy files (Dockerfile, .dockerignore, render.yaml, workflows). Nothing here
deploys anything or claims a live check."""

import io
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings
from django.db.utils import OperationalError
from django.urls import reverse

from config import health
from config.logs import JsonFormatter, ScrubFilter, scrub

ROOT = Path(__file__).resolve().parents[1]
SECRET_LIKE_TEXT = "postgres://vs:hunter2-pass@db.internal.example:5432/vs"


# --- /livez and /healthz (D81) ---


def test_health_routes_are_named_and_unprefixed() -> None:
    assert reverse("livez") == "/livez"
    assert reverse("healthz") == "/healthz"
    assert settings.MIDDLEWARE[0] == "config.health.HealthCheckMiddleware"


def test_livez_needs_no_database(client) -> None:
    """Not marked django_db: pytest-django fails any database access here."""
    response = client.get("/livez")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response["Cache-Control"] == "no-store"
    assert not response.cookies


def test_health_bypasses_host_check_and_https_redirect(client, settings) -> None:
    settings.SECURE_SSL_REDIRECT = True
    response = client.get("/livez", HTTP_HOST="unlisted-host.example")
    assert response.status_code == 200
    assert b"unlisted-host" not in response.content
    # Other pages still get the host check (400) - the bypass is for the two exact paths only.
    assert client.get("/livez/", HTTP_HOST="unlisted-host.example").status_code == 400


@pytest.mark.django_db
def test_healthz_ok_with_database(client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response["Cache-Control"] == "no-store"
    assert not response.cookies
    assert client.head("/healthz").status_code == 200


class _BrokenConnection:
    def cursor(self):
        raise OperationalError(f"connection failed: {SECRET_LIKE_TEXT} from 203.0.113.9")


def test_healthz_reports_unavailable_without_details(client, monkeypatch, caplog) -> None:
    monkeypatch.setattr(health, "connection", _BrokenConnection())
    with caplog.at_level(logging.WARNING, logger="config.health"):
        response = client.get("/healthz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert b"hunter2" not in response.content and b"db.internal" not in response.content
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "OperationalError" in logged
    assert "hunter2" not in logged and "203.0.113.9" not in logged


@pytest.mark.parametrize("path", ["/livez", "/healthz"])
def test_health_rejects_other_methods(client, path) -> None:
    response = client.post(path)
    assert response.status_code == 405
    assert response["Allow"] == "GET, HEAD"


# --- security headers and CSP (D82) ---


def test_middleware_order() -> None:
    mw = settings.MIDDLEWARE
    security = mw.index("django.middleware.security.SecurityMiddleware")
    assert mw[security + 1] == "whitenoise.middleware.WhiteNoiseMiddleware"
    assert "config.security.SecurityHeadersMiddleware" in mw


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", ["login", "tourist_check"])
def test_pages_carry_strict_csp(client, url_name) -> None:
    response = client.get(reverse(url_name))
    assert response.status_code == 200
    csp = response["Content-Security-Policy"]
    directives = dict(d.strip().split(" ", 1) for d in csp.split(";"))
    assert directives["default-src"] == "'none'"
    assert directives["script-src"] == "'self'"
    assert directives["style-src"] == "'self'"
    assert directives["frame-ancestors"] == "'none'"
    assert directives["form-action"] == "'self'"
    assert "unsafe" not in csp and "http" not in csp
    assert "camera=()" in response["Permissions-Policy"]
    assert response["X-Frame-Options"] == "DENY"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Referrer-Policy"] == "same-origin"


TEMPLATES = sorted((ROOT / "src" / "templates").rglob("*.html"))
CSP_BREAKERS = {
    "inline script": re.compile(r"<script(?![^>]*\bsrc=)[^>]*>", re.IGNORECASE),
    "style element": re.compile(r"<style\b", re.IGNORECASE),
    "style attribute": re.compile(r"\sstyle\s*=", re.IGNORECASE),
    "event handler": re.compile(r"\son[a-z]+\s*=", re.IGNORECASE),
    "javascript: URL": re.compile(r"javascript:", re.IGNORECASE),
    "third-party URL": re.compile(r"(?:src|href)\s*=\s*[\"']?(?:https?:)?//", re.IGNORECASE),
}


def test_templates_stay_compatible_with_the_csp() -> None:
    assert TEMPLATES, "no templates found"
    problems = [
        f"{path.relative_to(ROOT)}: {name}"
        for path in TEMPLATES
        for name, pattern in CSP_BREAKERS.items()
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert problems == []


# --- production settings (subprocess: settings are read once per process) ---

PROD_ENV = {
    "DJANGO_DEBUG": "0",
    # 50+ characters, no "django-insecure-" prefix: satisfies check --deploy (W009). Test only.
    "DJANGO_SECRET_KEY": "m11-test-only-" + "abcdefghij0123456789" * 3,
    "DJANGO_ALLOWED_HOSTS": "vs.example, www.vs.example",
    "DJANGO_CSRF_TRUSTED_ORIGINS": "https://vs.example",
    "DJANGO_CLIENT_IP_HEADER": "HTTP_X_FORWARDED_FOR",
    "DJANGO_TRUSTED_PROXY_HOPS": "1",
}


def _run(code: list[str], extra: dict[str, str] | None = None, drop: tuple[str, ...] = ()):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "DATABASE_"))}
    env.update(PROD_ENV, PYTHONPATH=str(ROOT / "src"), DJANGO_SETTINGS_MODULE="config.settings")
    env.update(extra or {})
    for key in drop:
        env.pop(key, None)
    return subprocess.run(
        [sys.executable, *code], env=env, capture_output=True, text=True, cwd=ROOT / "src"
    )


def test_production_settings_flags() -> None:
    code = """
import config.settings as s
assert s.DEBUG is False
assert s.ALLOWED_HOSTS == ['vs.example', 'www.vs.example'], s.ALLOWED_HOSTS
assert s.CSRF_TRUSTED_ORIGINS == ['https://vs.example']
assert s.SECURE_SSL_REDIRECT is True
assert s.SECURE_HSTS_SECONDS >= 31536000 and s.SECURE_HSTS_INCLUDE_SUBDOMAINS
assert s.SECURE_HSTS_PRELOAD is False
assert s.SECURE_PROXY_SSL_HEADER == ('HTTP_X_FORWARDED_PROTO', 'https')
assert s.SESSION_COOKIE_SECURE and s.CSRF_COOKIE_SECURE and s.SESSION_COOKIE_HTTPONLY
assert s.SECURE_CONTENT_TYPE_NOSNIFF and s.X_FRAME_OPTIONS == 'DENY'
backend = s.STORAGES['staticfiles']['BACKEND']
assert backend == 'whitenoise.storage.CompressedManifestStaticFilesStorage', backend
"""
    result = _run(["-c", code])
    assert result.returncode == 0, result.stderr


def test_production_settings_require_allowed_hosts() -> None:
    result = _run(["-c", "import config.settings"], drop=("DJANGO_ALLOWED_HOSTS",))
    assert result.returncode != 0 and "DJANGO_ALLOWED_HOSTS" in result.stderr


def test_ssl_redirect_can_be_turned_off_for_local_http_runs() -> None:
    code = "import config.settings as s; assert s.SECURE_SSL_REDIRECT is False"
    result = _run(["-c", code], {"DJANGO_SECURE_SSL_REDIRECT": "0"})
    assert result.returncode == 0, result.stderr


def test_debug_is_off_unless_explicitly_on() -> None:
    result = _run(
        ["-c", "import config.settings as s; assert s.DEBUG is False"], drop=("DJANGO_DEBUG",)
    )
    assert result.returncode == 0, result.stderr


def test_check_deploy_passes_with_production_env() -> None:
    result = _run(["manage.py", "check", "--deploy", "--fail-level", "WARNING"])
    assert result.returncode == 0, result.stdout + result.stderr


# --- logging without personal data (D84) ---


@pytest.mark.parametrize(
    ("raw", "leak"),
    [
        ("login from 203.0.113.45 failed", "203.0.113.45"),
        ("peer 2001:db8:85a3::8a2e:370:7334 closed", "2001:db8"),
        ("peer ::ffff:198.51.100.7 closed", "198.51.100.7"),
        ("full 2001:0db8:0000:0000:0000:ff00:0042:8329 seen", "2001:0db8"),
        ("mail priya.k@example.org bounced", "priya.k@example.org"),
        ("call +91 9876543210 now", "9876543210"),
        ("call 09876543210", "9876543210"),
        (f"could not connect: {SECRET_LIKE_TEXT}", "hunter2"),
        ("form password=Secret123 username=a", "Secret123"),
        ("Authorization: Bearer-abc123", "Bearer-abc123"),
        ("csrfmiddlewaretoken='tok-xyz'", "tok-xyz"),
        ("Cookie: sessionid=abcdef0123", "abcdef0123"),
    ],
)
def test_scrub_removes_personal_data_and_secrets(raw: str, leak: str) -> None:
    assert leak not in scrub(raw)


@pytest.mark.parametrize(
    "text",
    [
        "run 12 finished: 300 listings, 0.912 score, 12:30:45",
        "params m5-tuned-1 version 3.11",
        "Not Found: /officer/cases/12/",
    ],
)
def test_scrub_leaves_ordinary_text(text: str) -> None:
    assert scrub(text) == text


class _FakeRequest:
    META = {"REMOTE_ADDR": "198.51.100.23", "HTTP_COOKIE": "sessionid=s3cr3t"}

    def __repr__(self) -> str:
        return f"<Request from {self.META['REMOTE_ADDR']} {self.META['HTTP_COOKIE']}>"


def _emit(logger_name: str, level: int, msg: str, *args, exc_info=None, **extra) -> dict:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ScrubFilter())
    record = logging.getLogger(logger_name).makeRecord(
        logger_name, level, __file__, 1, msg, args, exc_info, extra=extra
    )
    handler.handle(record)
    line = stream.getvalue().strip()
    assert "\n" not in line  # one JSON object per line
    return json.loads(line)


def test_json_log_line_has_fixed_fields_and_no_request() -> None:
    entry = _emit(
        "django.request",
        logging.WARNING,
        "Not Found: %s",
        "/officer/cases/99/",
        status_code=404,
        request=_FakeRequest(),
    )
    assert set(entry) == {"ts", "level", "logger", "message", "status_code"}
    assert entry["message"] == "Not Found: /officer/cases/99/"
    assert entry["status_code"] == 404
    text = json.dumps(entry)
    assert "198.51.100.23" not in text and "s3cr3t" not in text


def test_exceptions_are_logged_scrubbed() -> None:
    try:
        raise OperationalError(f"{SECRET_LIKE_TEXT} client 203.0.113.77")
    except OperationalError:
        entry = _emit(
            "django.request", logging.ERROR, "Internal Server Error", exc_info=sys.exc_info()
        )
    assert "OperationalError" in entry["exc"]
    assert "hunter2" not in entry["exc"] and "203.0.113.77" not in entry["exc"]


def test_settings_route_all_logs_through_the_scrubbing_handler() -> None:
    conf = settings.LOGGING
    handler = conf["handlers"]["stdout"]
    assert handler["filters"] == ["scrub"] and handler["formatter"] == "json"
    assert conf["filters"]["scrub"]["()"] == "config.logs.ScrubFilter"
    assert conf["formatters"]["json"]["()"] == "config.logs.JsonFormatter"
    assert conf["root"]["handlers"] == ["stdout"]
    assert conf["loggers"]["django"] == {
        "handlers": ["stdout"],
        "level": settings.LOG_LEVEL,
        "propagate": False,
    }
    assert set(conf["handlers"]) == {"stdout"}  # no mail_admins or file handlers


def test_no_error_tracking_dependency() -> None:
    """Sentry is not approved (D84, cut order item 4)."""
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "sentry" not in requirements


# --- deploy files: static checks only (the image is built by CI, not here) ---


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_dockerfile_ships_runtime_data_and_runs_as_non_root() -> None:
    from matching.gazetteer import DEFAULT_GAZETTEER, DEFAULT_LOCALITIES

    dockerfile = _read("Dockerfile")
    assert (
        "data/synthetic/gazetteer.csv" in dockerfile and DEFAULT_GAZETTEER.name == "gazetteer.csv"
    )
    assert (
        "data/synthetic/localities.csv" in dockerfile
        and DEFAULT_LOCALITIES.name == "localities.csv"
    )
    assert "COPY data/synthetic/out ./data/synthetic/out" in dockerfile
    # The gazetteer path resolves to <WORKDIR /app>/data/synthetic, next to src/.
    assert DEFAULT_GAZETTEER.parent == ROOT / "data" / "synthetic"
    assert "collectstatic --noinput" in dockerfile
    assert re.search(r"^USER app$", dockerfile, re.MULTILINE)
    user_line = dockerfile.index("USER app")
    assert dockerfile.index("CMD [") > user_line
    assert "HEALTHCHECK" in dockerfile and "/livez" in dockerfile
    assert "FROM python:3.11" in dockerfile


def test_dockerignore_allows_exactly_what_the_image_needs() -> None:
    lines = [
        line.strip()
        for line in _read(".dockerignore").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert lines[0] == "*"
    allowed = {line[1:] for line in lines if line.startswith("!")}
    assert allowed == {
        "requirements.txt",
        "src",
        "data/synthetic/gazetteer.csv",
        "data/synthetic/localities.csv",
        "data/synthetic/out",
        "scripts/docker-start.sh",
    }
    for path in allowed:
        assert (ROOT / path).exists(), path


def test_start_script_keeps_access_log_off_and_migrates() -> None:
    script = _read("scripts/docker-start.sh")
    commands = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    assert "access-log" not in commands and "access_log" not in commands
    assert "manage.py migrate --noinput" in commands and "createcachetable" in commands
    assert "exec gunicorn config.wsgi:application" in commands
    assert "\r" not in script


SECRET_ENV_NAMES = ("DJANGO_SECRET_KEY", "DATABASE_URL")


def test_render_blueprint_has_names_only() -> None:
    blueprint = _read("render.yaml")
    assert "plan: free" in blueprint and "runtime: docker" in blueprint
    assert "healthCheckPath: /livez" in blueprint
    # Secrets: never a literal value in the file.
    for name in SECRET_ENV_NAMES + ("DJANGO_ALLOWED_HOSTS", "DJANGO_CSRF_TRUSTED_ORIGINS"):
        block = re.search(rf"- key: {name}\n((?:\s+\w+:.*\n)+)", blueprint)
        assert block, name
        assert "value:" not in block.group(1), name
        assert "sync: false" in block.group(1) or "generateValue: true" in block.group(1), name
    assert re.search(r"- key: DJANGO_DEBUG\n\s+value: \"0\"", blueprint)


def test_backup_workflow_uses_secrets_only() -> None:
    workflow = _read(".github/workflows/backup.yml")
    assert "schedule:" in workflow and "workflow_dispatch:" in workflow
    for name in (
        "BACKUP_DATABASE_URL",
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET",
    ):
        assert f"secrets.{name}" in workflow, name
    assert "pip install" not in workflow  # runner tools only, no Python dependency
    # The only credential URL is the throwaway restore-test container on the runner itself.
    assert not re.search(r"postgres(?:ql)?://[^$\s:]+:[^$\s@]+@(?!localhost[:/])", workflow)
    assert "scripts/restore-test.sh" in workflow


def test_deploy_job_is_disabled_by_default() -> None:
    ci = _read(".github/workflows/ci.yml")
    deploy = ci[ci.index("\n  deploy:") :]
    assert "vars.ENABLE_RENDER_DEPLOY == 'true'" in deploy
    assert "secrets.RENDER_DEPLOY_HOOK_URL" in deploy
    assert "github.ref == 'refs/heads/main'" in deploy
    assert "\n  docker:" in ci and "docker build" in ci
    assert "docker push" not in ci
