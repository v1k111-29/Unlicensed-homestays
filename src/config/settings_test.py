"""Test settings: a fixed non-secret key so tests run without a .env. Never use in production."""

import os

# 50+ characters: production settings refuse shorter keys outside DEBUG (D89). Test only.
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-not-a-secret-" + "0123456789" * 3)
os.environ.setdefault("DJANGO_CLIENT_IP_HEADER", "REMOTE_ADDR")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "testserver")
# The test client speaks plain HTTP; HTTPS redirect is checked by its own tests.
os.environ.setdefault("DJANGO_SECURE_SSL_REDIRECT", "0")

from config.settings import *  # noqa: E402,F403

# The manifest storage needs `collectstatic` output; tests render templates without it.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
# No collectstatic output in tests: WhiteNoise looks files up per request instead of scanning
# STATIC_ROOT at start-up (which would warn that the folder is missing).
WHITENOISE_AUTOREFRESH = True
