"""Response security headers that Django 5.2 does not set itself (M11, D82).

Django 5.2 has no built-in Content-Security-Policy (it arrives in Django 6, which needs Python
3.12). The policy is strict: everything from this origin only, no inline scripts or styles, no
third-party hosts (system fonts only, UI brief / D70), no framing. Templates must stay free of
``<script>`` bodies, ``style=`` attributes and ``on*=`` handlers; a test scans them.
"""

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse

# The Content-Security-Policy sent with every response. The browser refuses anything the policy
# does not allow, which limits the damage if an attacker ever injects markup into a page.
DEFAULT_CSP = "; ".join(
    [
        # Deny by default: every resource type not named below is blocked.
        "default-src 'none'",
        # No inline or third-party scripts: an injected <script> would not run.
        "script-src 'self'",
        # No inline <style> or style= attributes, so injected CSS cannot restyle the page.
        "style-src 'self'",
        "img-src 'self'",
        "font-src 'self'",
        # Scripted requests (fetch, XHR) may only reach this site, so data cannot be sent elsewhere.
        "connect-src 'self'",
        # Forms may only submit back to this site.
        "form-action 'self'",
        # No one may frame these pages, which stops clickjacking.
        "frame-ancestors 'none'",
        # Stops an injected <base> tag from redirecting relative URLs elsewhere.
        "base-uri 'none'",
    ]
)

# No page needs these browser features, so they are switched off for every page.
DEFAULT_PERMISSIONS_POLICY = "camera=(), geolocation=(), microphone=(), payment=(), usb=()"


class SecurityHeadersMiddleware:
    """Adds Content-Security-Policy and Permissions-Policy unless a view already set them.

    Placed early in MIDDLEWARE (see config.settings), so every response passes through it."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """Read the policy strings once, at start-up, from settings or the defaults above."""
        self.get_response = get_response
        self.csp = getattr(settings, "CONTENT_SECURITY_POLICY", DEFAULT_CSP)
        self.permissions = getattr(settings, "PERMISSIONS_POLICY", DEFAULT_PERMISSIONS_POLICY)

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Run the rest of the chain, then add the two headers to the response."""
        response = self.get_response(request)
        # setdefault: a view that sets its own header keeps it. An empty setting turns it off.
        if self.csp:
            response.headers.setdefault("Content-Security-Policy", self.csp)
        if self.permissions:
            response.headers.setdefault("Permissions-Policy", self.permissions)
        return response
