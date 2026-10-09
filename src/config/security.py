"""Response security headers that Django 5.2 does not set itself (M11, D78).

Django 5.2 has no built-in Content-Security-Policy (it arrives in Django 6, which needs Python
3.12). The policy is strict: everything from this origin only, no inline scripts or styles, no
third-party hosts (system fonts only, UI brief / D70), no framing. Templates must stay free of
``<script>`` bodies, ``style=`` attributes and ``on*=`` handlers; a test scans them.
"""

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse

DEFAULT_CSP = "; ".join(
    [
        "default-src 'none'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self'",
        "font-src 'self'",
        "connect-src 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
    ]
)

# No page needs these browser features.
DEFAULT_PERMISSIONS_POLICY = "camera=(), geolocation=(), microphone=(), payment=(), usb=()"


class SecurityHeadersMiddleware:
    """Adds Content-Security-Policy and Permissions-Policy unless a view already set them."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self.csp = getattr(settings, "CONTENT_SECURITY_POLICY", DEFAULT_CSP)
        self.permissions = getattr(settings, "PERMISSIONS_POLICY", DEFAULT_PERMISSIONS_POLICY)

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if self.csp:
            response.headers.setdefault("Content-Security-Policy", self.csp)
        if self.permissions:
            response.headers.setdefault("Permissions-Policy", self.permissions)
        return response
