"""Parse DATABASE_URL into a Django DATABASES entry. Standard library only (D31).

Accepted form: postgres://USER:PASSWORD@HOST:PORT/NAME?sslmode=require
(scheme `postgres` or `postgresql`). Percent-encoded user/password are decoded.
"""

from urllib.parse import parse_qsl, unquote, urlsplit

POSTGRES_SCHEMES = {"postgres", "postgresql"}


def parse_database_url(url: str) -> dict:
    parts = urlsplit(url)
    if parts.scheme not in POSTGRES_SCHEMES:
        raise ValueError(
            f"DATABASE_URL scheme must be postgres:// or postgresql://, got {parts.scheme!r}"
        )
    name = unquote(parts.path.lstrip("/"))
    if not name:
        raise ValueError("DATABASE_URL must name a database, e.g. postgres://u:p@localhost/db")
    config: dict = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": name,
        "USER": unquote(parts.username or ""),
        "PASSWORD": unquote(parts.password or ""),
        "HOST": parts.hostname or "",
        "PORT": str(parts.port or ""),
        "CONN_MAX_AGE": 60,
    }
    options = dict(parse_qsl(parts.query))
    if options:
        config["OPTIONS"] = options
    return config
