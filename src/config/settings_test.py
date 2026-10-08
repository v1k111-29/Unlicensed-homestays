"""Test settings: a fixed non-secret key so tests run without a .env. Never use in production."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-not-a-secret")
os.environ.setdefault("DJANGO_CLIENT_IP_HEADER", "REMOTE_ADDR")

from config.settings import *  # noqa: E402,F403
