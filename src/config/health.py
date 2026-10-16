"""Health endpoints (M11, D81). Public, no auth, no sensitive information.

- ``/livez``: the process answers. Never touches the database. Used by the Docker HEALTHCHECK
  and the Render health check, which poll often: a database check there would keep the free
  Neon database awake around the clock (D81, Q9).
- ``/healthz``: the process answers and the database runs ``SELECT 1``. Used by the uptime
  monitor. 200 ``{"status": "ok"}`` or 503 ``{"status": "unavailable"}``; the reason is
  logged (exception class only), never returned.

``HealthCheckMiddleware`` sits first in ``MIDDLEWARE`` and answers these two exact paths before
host validation, the HTTPS redirect, sessions and CSRF run, so a local probe
(``http://127.0.0.1:<port>/livez``) works whatever ``ALLOWED_HOSTS`` is, and no cookie is set.
The responses never echo the Host header or any request data. The same views are routed in
``config.urls`` (on the public allowlist) so ``reverse()`` and the route-walk test see them.
"""

import logging
from collections.abc import Callable

from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse

logger = logging.getLogger(__name__)

ALLOWED_METHODS = ("GET", "HEAD")


def _response(status: str, code: int) -> HttpResponse:
    """A small JSON answer. The headers stop caches from storing it and browsers from guessing
    its type."""
    response = JsonResponse({"status": status}, status=code)
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _method_not_allowed() -> HttpResponse:
    """A 405 reply that lists the methods this path accepts."""
    response = HttpResponse(status=405)
    response["Allow"] = ", ".join(ALLOWED_METHODS)
    return response


def livez(request: HttpRequest) -> HttpResponse:
    """Liveness probe: answers 200 as long as the process runs. Never touches the database."""
    if request.method not in ALLOWED_METHODS:
        return _method_not_allowed()
    return _response("ok", 200)


def healthz(request: HttpRequest) -> HttpResponse:
    """Readiness probe: answers 200 only if a trivial database query succeeds, else 503."""
    if request.method not in ALLOWED_METHODS:
        return _method_not_allowed()
    # The database is checked here, not in livez, so frequent probes do not wake the database.
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:  # any database failure means "unavailable"
        # Class name only: driver messages can carry host names or connection details.
        logger.warning("health check: database unavailable (%s)", type(exc).__name__)
        return _response("unavailable", 503)
    return _response("ok", 200)


# Exact paths only. Anything else (including the same path with a trailing slash) goes on
# through the normal middleware chain.
HEALTH_PATHS: dict[str, Callable[[HttpRequest], HttpResponse]] = {
    "/livez": livez,
    "/healthz": healthz,
}


class HealthCheckMiddleware:
    """Answer the two health paths before anything else runs (see module docstring)."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """Store the next handler in the middleware chain."""
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Answer a health path directly, or pass every other request down the chain."""
        view = HEALTH_PATHS.get(request.path_info)
        if view is not None:
            return view(request)
        return self.get_response(request)
