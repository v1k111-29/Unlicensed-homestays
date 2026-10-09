"""M10 x M11 integration: the health endpoints answer before the language/redirect logic and the
host check, and the CSP headers reach the language-prefixed pages and the M10 error pages."""

import pytest
from django.http import HttpRequest, HttpResponse
from django.urls import path


def _boom(request: HttpRequest) -> HttpResponse:
    raise RuntimeError("integration test: forced server error")


# Used only by the 500 test below (pytest.mark.urls); same handler as the real URLconf.
urlpatterns = [path("boom", _boom)]
handler500 = "config.views.server_error"


@pytest.mark.django_db
@pytest.mark.parametrize("path_", ["/livez", "/healthz"])
def test_health_ignores_language_host_and_https(client, settings, path_) -> None:
    settings.SECURE_SSL_REDIRECT = True
    response = client.get(path_, HTTP_HOST="unlisted-host.example", HTTP_ACCEPT_LANGUAGE="ta")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert not response.cookies


def test_english_prefix_redirect_of_health_path_stays_local(client) -> None:
    response = client.get("/en/livez")
    assert response.status_code in (301, 302)
    assert response["Location"] == "/livez"


@pytest.mark.django_db
@pytest.mark.parametrize("url", ["/ta/check/", "/check/", "/ta/no-such-page/"])
def test_csp_on_language_pages_and_404(client, url) -> None:
    response = client.get(url)
    assert response.status_code in (200, 404)
    assert "default-src 'none'" in response["Content-Security-Policy"]
    assert "Permissions-Policy" in response


@pytest.mark.urls(__name__)
def test_csp_on_500_page(client) -> None:
    client.raise_request_exception = False
    response = client.get("/boom")
    assert response.status_code == 500
    assert "default-src 'none'" in response["Content-Security-Policy"]


def test_image_ships_compiled_catalog_without_gettext() -> None:
    """The Dockerfile copies src/ (which holds the committed django.mo, D78) and needs no msgfmt;
    the .dockerignore allowlist must not drop .mo files."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert (root / "src/locale/ta/LC_MESSAGES/django.mo").is_file()
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY src ./src" in dockerfile
    assert "msgfmt" not in dockerfile and "compilemessages" not in dockerfile
    ignore = [
        ln.strip()
        for ln in (root / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    assert "!src" in ignore
    assert not any(ln.endswith(".mo") or "locale" in ln for ln in ignore)
