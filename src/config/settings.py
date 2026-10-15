"""Django settings. All secrets and per-environment values come from environment variables.

Required in production: DJANGO_SECRET_KEY, DATABASE_URL. See .env.example.

Django reads this module through DJANGO_SETTINGS_MODULE. Most values are fixed here on purpose,
so a reviewer can read the whole security setup in one file. DEBUG (from DJANGO_DEBUG) turns
on local-development shortcuts. Each start-up check that refuses to run names the environment
variable to set.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from config.dburl import parse_database_url

SRC_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SRC_DIR.parent

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"

# The key signs sessions, CSRF tokens and the HMACs used for throttling and audit, so it must
# be random and secret in production.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY (or DJANGO_DEBUG=1 for local work).")
    SECRET_KEY = "insecure-local-debug-only"
elif not DEBUG and (len(SECRET_KEY) < 50 or "change-me" in SECRET_KEY.lower()):
    # A placeholder or short key would make sessions, CSRF and the address HMACs guessable
    # (D89). DEBUG keeps any key for local work.
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY is a placeholder or shorter than 50 characters. Generate a random "
        "value (see .env.example)."
    )


def _env_list(name: str) -> list[str]:
    """Comma-separated environment variable as a list; blanks and spaces dropped."""
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


# Host names this site answers to. Django rejects requests for any other host name.
ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS")
if DEBUG:
    ALLOWED_HOSTS += ["localhost", "127.0.0.1"]
elif not ALLOWED_HOSTS:
    # Fail at start-up instead of answering every request with 400 (M11).
    raise ImproperlyConfigured("Set DJANGO_ALLOWED_HOSTS (comma-separated host names).")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "registry",
    "listings",
    "matching",
    "reviews",
    "audit",
    "tourist",
]

MIDDLEWARE = [
    # First: answers /livez and /healthz before host checks, HTTPS redirect and sessions (D81).
    "config.health.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Static files from the image (D83); directly after SecurityMiddleware per WhiteNoise docs.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "config.security.SecurityHeadersMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "accounts.middleware.AbsoluteSessionLifetimeMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [SRC_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
                "config.context_processors.language_links",
            ],
        },
    },
]

# PostgreSQL only (D4, D39). Without DATABASE_URL, Django falls back to its dummy backend:
# imports and non-DB tests work; anything touching the DB fails with a clear error.
_database_url = os.environ.get("DATABASE_URL", "")
DATABASES = {"default": parse_database_url(_database_url)} if _database_url else {}

AUTH_USER_MODEL = "accounts.User"
# Django uses the first hasher for new passwords. PBKDF2 stays in the list so that existing
# hashes still check; Django upgrades them when a user signs in.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("ta", "Tamil")]
LOCALE_PATHS = [SRC_DIR / "locale"]
USE_I18N = True
TIME_ZONE = "Asia/Kolkata"
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = REPO_ROOT / "staticfiles"
STATICFILES_DIRS = [SRC_DIR / "static"]
# Hashed, compressed files built by `collectstatic` in the Docker image and served by
# WhiteNoise with far-future cache headers (D83). Tests use plain storage (settings_test).
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Authentication and sessions (M6, docs/security-and-privacy.md §2, D57-D59) ---
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# HttpOnly keeps the session cookie away from page scripts. SameSite=Lax limits cross-site sends.
# Secure (HTTPS only) is on everywhere except local DEBUG work.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
# Idle timeout: 30 minutes without a request ends the session; closing the browser ends it too.
SESSION_COOKIE_AGE = 30 * 60
# Saving on every request is what makes the idle timeout a true "no activity" timer.
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
# Absolute lifetime: a session ends 8 hours after login however active it is (middleware).
SESSION_ABSOLUTE_SECONDS = 8 * 60 * 60
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SAMESITE = "Lax"

# Security headers. CSP and Permissions-Policy: config.security (D82); the policy strings are
# the defaults there and can be replaced here as CONTENT_SECURITY_POLICY / PERMISSIONS_POLICY.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
if not DEBUG:
    # HTTPS only (M11, D82). DJANGO_SECURE_SSL_REDIRECT=0 only for a local plain-HTTP container
    # run; the hosted service keeps the default. /livez and /healthz are answered before the
    # redirect (config.health), so local probes and the host's health check work over HTTP.
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "1") == "1"
    # One year, this host and its sub-hosts. Not preloaded: a preload entry is hard to undo and
    # the demo host is a subdomain of the hosting provider (security.W021 silenced below).
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", str(365 * 24 * 60 * 60)))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = False
    SILENCED_SYSTEM_CHECKS = ["security.W021"]

# Request size limits (documented in docs/deploy-runbook.md): Django's defaults stay
# (DATA_UPLOAD_MAX_MEMORY_SIZE 2.5 MB for non-file bodies, DATA_UPLOAD_MAX_NUMBER_FIELDS 1000);
# CSV files are capped at 2 MB by ingest.csvtools.CappedUploadHandler (D67).

# 5 failed logins within 15 minutes lock the account and the client address for the rest of
# that window (essentialfeatures.md O1, D58).
LOGIN_THROTTLE = {"max_failures": 5, "window_seconds": 15 * 60}

# Public tourist check (M9, D75, D88): at most this many checks per client address per window,
# per Gunicorn worker. Counted in the per-process memory cache "tourist_throttle" (below) under
# an HMAC of the address; nothing about the address is written to the database.
TOURIST_THROTTLE = {"max_checks": 20, "window_seconds": 5 * 60}

# Where the real client address comes from (D62). "REMOTE_ADDR" = direct connection; behind a
# proxy, the header the proxy appends to, e.g. "HTTP_X_FORWARDED_FOR", plus the number of
# trusted proxies that append to it. Required outside DEBUG: a wrong value either lets clients
# spoof the address limit or puts every user behind one proxy address.
CLIENT_IP_HEADER = os.environ.get("DJANGO_CLIENT_IP_HEADER", "REMOTE_ADDR" if DEBUG else "")
TRUSTED_PROXY_HOPS = int(os.environ.get("DJANGO_TRUSTED_PROXY_HOPS", "1"))
if not CLIENT_IP_HEADER:
    raise ImproperlyConfigured(
        "Set DJANGO_CLIENT_IP_HEADER to REMOTE_ADDR (no proxy) or the proxy header, "
        "e.g. HTTP_X_FORWARDED_FOR (see .env.example)."
    )
if not DEBUG:
    # Origins the browser may send form posts from, so CSRF checks accept the hosted site.
    CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
    if CLIENT_IP_HEADER != "REMOTE_ADDR":
        # Behind a TLS-terminating proxy that sets this header (and strips client copies).
        # Without this, Django would see every request as plain HTTP, not HTTPS.
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# "default": database cache, shared by all workers, so the login address limit is global
# (D58) and pending uploads survive between workers (D68). The table is created by
# `python tasks.py migrate` (createcachetable) and by the test runner; backups skip its rows
# (D88). "tourist_throttle": per-process memory only, so the tourist address HMAC never reaches
# a table or a backup; the limit is per worker (D88).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
    },
    "tourist_throttle": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "tourist-throttle",
    },
}

# --- Demo sign-in hint (D96): the login page shows these accounts only when both values of a
# pair are set, so evaluators of the synthetic demo can sign in. Environment only, never in
# code (AGENTS.md rule 8). Leave unset for any deployment with real data. ---
# Each list entry is built only when both its username and password variables are set.
DEMO_LOGIN_ACCOUNTS = [
    {"role": role, "username": username, "password": password}
    for role in ("officer", "admin")
    if (username := os.environ.get(f"DEMO_{role.upper()}_USERNAME", "").strip())
    and (password := os.environ.get(f"DEMO_{role.upper()}_PASSWORD", ""))
]

# --- Logging (M11, D84): JSON lines on stdout, personal data scrubbed (config.logs). No
# request objects, client addresses or form data are written. Gunicorn's access log stays off
# (scripts/docker-start.sh), so the app writes no tourist addresses (AGENTS.md rule 5). ---
LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL", "INFO").upper()
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"scrub": {"()": "config.logs.ScrubFilter"}},
    "formatters": {"json": {"()": "config.logs.JsonFormatter"}},
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "json",
            "filters": ["scrub"],
        }
    },
    "root": {"handlers": ["stdout"], "level": LOG_LEVEL},
    "loggers": {
        # Replaces Django's default handlers (console in DEBUG only, mail_admins).
        "django": {"handlers": ["stdout"], "level": LOG_LEVEL, "propagate": False},
    },
}
