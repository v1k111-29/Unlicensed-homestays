"""Site-level views (M10): the home page redirect and the server-error page."""

from __future__ import annotations

import logging
import secrets

from django.http import HttpRequest, HttpResponse, HttpResponseServerError
from django.shortcuts import redirect
from django.template import loader
from django.views.decorators.cache import never_cache

logger = logging.getLogger("verified_stays.errors")


@never_cache
def home(request: HttpRequest) -> HttpResponse:
    """``/`` (and ``/ta/``): the tourist check for visitors, the dashboard once signed in.
    Public by design (on the route-walk allowlist): it only redirects."""
    if request.user.is_authenticated:
        return redirect("dashboard")
    return redirect("tourist_check")


def english_prefix(request: HttpRequest, rest: str = "") -> HttpResponse:
    """``/en/<path>`` -> ``/<path>``: English pages have no prefix (D77), but an ``/en/`` link
    (essentialfeatures.md T2) still works. Public: it only redirects within this site. Leading
    slashes and backslashes are stripped so the target can never become ``//host``."""
    target = "/" + rest.lstrip("/\\")
    query = request.META.get("QUERY_STRING", "")
    return redirect(target + (f"?{query}" if query else ""))


def server_error(request: HttpRequest) -> HttpResponse:
    """handler500: plain message, retry link and an error ID that also goes to the log, so a
    report can be matched to the traceback. Rendered without context processors or the
    database, because whatever failed may be one of them. No client address is logged."""
    error_id = secrets.token_hex(6)
    logger.error("server error id=%s method=%s path=%s", error_id, request.method, request.path)
    retry = request.get_full_path() if request.method == "GET" else request.path
    html = loader.get_template("500.html").render({"error_id": error_id, "retry_url": retry})
    return HttpResponseServerError(html)
