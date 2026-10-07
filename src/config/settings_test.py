"""Test settings: a fixed non-secret key so tests run without a .env. Never use in production."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-not-a-secret")

from config.settings import *  # noqa: E402,F403
