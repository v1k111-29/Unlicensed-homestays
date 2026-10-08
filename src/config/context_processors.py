"""Template context shared by every page (M10)."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest
from django.urls import NoReverseMatch, Resolver404, resolve, reverse, translate_url
from django.utils.translation import get_language, get_language_info, override

# POST-only routes: a language link on a page rendered by one of these (e.g. a refused
# decision, status 400/409) points at the page the form came from, so it never lands on 405.
POST_ONLY_FALLBACK = {
    "case_decide": "case_detail",
    "run_create": "runs",
    "upload_listings_confirm": "upload_listings",
    "upload_listings_cancel": "upload_listings",
    "upload_registry_confirm": "upload_registry",
    "upload_registry_cancel": "upload_registry",
}


def _same_page_in(request: HttpRequest, code: str) -> str:
    """The current page's URL in language ``code``; the home page when the current URL does
    not resolve (404 pages)."""
    try:
        match = resolve(request.path_info)
    except Resolver404:
        match = None
    if match is not None and match.url_name in POST_ONLY_FALLBACK:
        with override(code):
            return reverse(POST_ONLY_FALLBACK[match.url_name], kwargs=match.kwargs)
    if match is None:
        with override(code):
            try:
                return reverse("home")
            except NoReverseMatch:  # test URLconfs without the site routes
                return "/"
    # Keep GET filters (queue, pagination); a POST body is never put into a URL.
    query = request.META.get("QUERY_STRING", "") if request.method == "GET" else ""
    return translate_url(request.path + (f"?{query}" if query else ""), code)


def language_links(request: HttpRequest) -> dict:
    """Links for the header language switch: plain GET links, no JavaScript, no cookie (the
    URL prefix carries the language; D77)."""
    current = get_language()
    links = []
    for code, _name in settings.LANGUAGES:
        links.append(
            {
                "code": code,
                "name": get_language_info(code)["name_local"],
                "url": _same_page_in(request, code),
                "current": code == current,
            }
        )
    return {"language_links": links}
